/* ==========================================================================
   Varuvi Admin — dashboard logic
   Auth: HTTP Basic (see backend/auth.py). Credentials are base64-encoded
   and kept in sessionStorage only (cleared on tab close / sign-out) — never
   written to localStorage, never sent anywhere except this API's own host.
   ========================================================================== */

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "http://localhost:8000" : "";
const AUTH_KEY = "varuvi_admin_auth"; // sessionStorage key holding "Basic <base64>"
const USER_KEY = "varuvi_admin_user"; // sessionStorage key holding the typed username, display only

const PAGE_SIZE = 20;

const state = {
  filters: { search: "", status: "", branch_id: "", department_id: "", date_from: "", date_to: "" },
  offset: 0,
  total: 0,
};

const adminState = {
  doctorEditId: null,
  branchEditId: null,
  departmentEditId: null,
  patientEditId: null,
  branches: [],
  departments: [],
  patients: [],
};

const convState = {
  search: "",
  source: "",
  conversations: [],
};

const SOURCE_LABEL = {
  WEB: "Website widget",
  WHATSAPP: "WhatsApp bot",
  CHATBOT: "AI chatbot",
};

const TAB_META = {
  booking: { title: "Bookings", sub: "Live appointment activity across every branch" },
  doctors: { title: "Doctors", sub: "Manage the doctor roster and public availability" },
  branches: { title: "Branches", sub: "Manage branches and see who's assigned where" },
  departments: { title: "Departments", sub: "Manage hospital departments" },
  patients: { title: "Registered Patients", sub: "View and manage registered patients and their medical history." },
  conversations: { title: "Conversations", sub: "Full chat history across the web widget, WhatsApp bot, and AI chatbot" },
  notifications: { title: "Notifications", sub: "Manage credentials for SMS and Email notifications" },
  roles: { title: "Roles & Permissions", sub: "Manage system access and configure custom roles" },
};

// ---------------------------------------------------------------------------
// Auth-aware fetch helper
// ---------------------------------------------------------------------------

function getAuthHeader() {
  return sessionStorage.getItem(AUTH_KEY);
}

async function adminApi(path, options = {}) {
  const auth = getAuthHeader();

   console.log(`adminAPI: ${API_BASE}${path}`);

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: auth } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    clearAuth();
    showLogin("Session expired or credentials were rejected. Please sign in again.");
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    let msg = "API Error";
    try {
      const errData = await res.json();
      if (errData.detail) {
          msg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
      } else {
          msg = errData.message || JSON.stringify(errData);
      }
    } catch (_) {}
    throw new Error(msg);
  }
  return await res.json();
}

// A plain (unauthenticated) call, for the public lookups used by filter dropdowns.
async function publicApi(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Login / logout
// ---------------------------------------------------------------------------

function clearAuth() {
  if (window.sseConnection) {
    window.sseConnection.close();
    window.sseConnection = null;
  }
  sessionStorage.removeItem(AUTH_KEY);
  sessionStorage.removeItem(USER_KEY);
  sessionStorage.removeItem("active_tab");
  sessionStorage.removeItem("ROLES");
  sessionStorage.removeItem("PERMISSIONS");
}

function showLogin(errorMessage) {
  document.getElementById("adminShell").hidden = true;
  document.getElementById("loginShell").hidden = false;
  const err = document.getElementById("loginError");
  if (errorMessage) {
    err.textContent = errorMessage;
    err.hidden = false;
  } else {
    err.hidden = true;
  }
}

function hasPermission(perm) {
  const roles = JSON.parse(sessionStorage.getItem('ROLES') || '[]');
  if (roles.includes('ADMIN') || roles.includes('SUPER_ADMIN')) return true;
  const perms = JSON.parse(sessionStorage.getItem('PERMISSIONS') || '[]');
  return perms.includes('*') || perms.includes(perm);
}

function applyRBAC() {
  const tabPerms = {
    'booking': 'APPOINTMENT_READ',
    'doctors': 'DOCTOR_READ',
    'branches': 'BRANCH_READ',
    'departments': 'DEPARTMENT_READ',
    'patients': 'PATIENT_READ',
    'conversations': 'CONVERSATION_READ',
    'notifications': 'ROLE_MANAGE',
    'roles': 'ROLE_MANAGE',
    'role-users': 'USER_MANAGE'
  };

  document.querySelectorAll(".sidebar-nav .nav-item").forEach(btn => {
    const tab = btn.dataset.tab;
    const required = tabPerms[tab];
    if (!required || hasPermission(required)) {
      btn.style.display = 'flex';
    } else {
      btn.style.display = 'none';
    }
  });

  const active = sessionStorage.getItem("active_tab");
  if (active && tabPerms[active] && !hasPermission(tabPerms[active])) {
    setActiveTab("booking"); 
  }
}

function connectSSE() {
  if (window.sseConnection) return;
  window.sseConnection = new EventSource(`${API_BASE}/events`);
  window.sseConnection.onmessage = async (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.event === "role_permissions_changed") {
        const roles = JSON.parse(sessionStorage.getItem('ROLES') || '[]');
        if (roles.includes(data.payload.role_name)) {
          const me = await adminApi("/auth/me");
          sessionStorage.setItem('PERMISSIONS', JSON.stringify(me.permissions || []));
          applyRBAC();
        }
      }
    } catch(err) {
      console.error("SSE Error:", err);
    }
  };
}

async function showDashboard() {
  document.getElementById("loginShell").hidden = true;
  document.getElementById("adminShell").hidden = false;
  paintSidebarUser();
  paintHeaderDate();
  applyRBAC();
  connectSSE();
  await loadAdminLookupData();

  const savedTab = sessionStorage.getItem("active_tab") || "booking";
  setActiveTab(savedTab);
}

// Purely cosmetic — who's signed in, and today's date in the header chip.
function paintSidebarUser() {
  const userStr = sessionStorage.getItem(USER_KEY);
  let name = "Admin";
  let role = "Staff account";

  if (userStr) {
    try {
      const userObj = JSON.parse(userStr);
      if (userObj.name) name = userObj.name;
      if (userObj.role) {
        role = userObj.role.replace('_', ' ').toLowerCase();
        role = role.charAt(0).toUpperCase() + role.slice(1);
      }
    } catch (e) {
      name = userStr; // fallback if it was a plain string
    }
  }

  const nameEl = document.getElementById("sidebarUserName");
  const avatarEl = document.getElementById("sidebarAvatar");
  const roleEl = document.querySelector(".sidebar-user .user-role");

  if (nameEl) nameEl.textContent = name;
  if (roleEl) roleEl.textContent = role;
  if (avatarEl) avatarEl.textContent = name.trim().charAt(0).toUpperCase() || "A";
}

function paintHeaderDate() {
  const el = document.getElementById("headerDate");
  if (!el) return;
  el.textContent = new Date().toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Tab switching — a single, plain, globally-callable function.
// Wired directly via onclick="setActiveTab('booking')" in the HTML so it
// never depends on event-listener setup timing or delegation quirks.
// ---------------------------------------------------------------------------

function setActiveTab(tabName) {
    sessionStorage.setItem("active_tab", tabName);

    document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle(
            "active",
            panel.id === `${tabName}Tab`
        );
    });

    document.querySelectorAll(".sidebar-nav .nav-item").forEach((btn) => {
        btn.classList.toggle(
            "active",
            btn.dataset.tab === tabName
        );
    });

    const meta = TAB_META[tabName];
    if (meta) {
        const titleEl = document.getElementById("pageTitle");
        const subEl = document.getElementById("pageSub");
        if (titleEl) titleEl.textContent = meta.title;
        if (subEl) subEl.textContent = meta.sub;
    }

    if (tabName === "branches") {
        loadBranches();
        showBranchForm(false);

    } else if (tabName === "departments") {
        loadAdminDepartments();
        showDepartmentForm(false);

    } else if (tabName === "doctors") {
        loadDoctorManagement();
        showDoctorForm(false);

    } else if (tabName === "booking") {
        loadStats();
        loadBookings();

    } else if (tabName === "patients") {
        loadPatients();

    } else if (tabName === "conversations") {
        loadConversations();

    } else if (tabName === "notifications") {
        loadNotificationConfig();
        loadWhatsappConfig();
        loadAiProviderConfig();
    } else if (tabName === "roles") {
        loadRolesAndPermissions();
    } else if (tabName === "role-users") {
        loadRoleUsers();
    }

    // Scroll the content pane back to the top on every tab switch.
    const main = document.getElementById("adminMain");
    if (main) main.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });

    if (isMobileViewport()) {
        closeMobileDrawer();
    }
}

function showDoctorForm(show) {
  const panel = document.getElementById("doctorModal");
  if (!panel) return;
  panel.hidden = !show;
}

function showBranchForm(show) {
  const panel = document.getElementById("branchModal");
  if (!panel) return;
  panel.hidden = !show;
}
function wireSidebarTabs() {
  document.querySelectorAll(".sidebar-nav .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabName = btn.dataset.tab;
      if (tabName) setActiveTab(tabName);
    });
  });
}
// Expose globally so the inline onclick="setActiveTab(...)" handlers can find it
// no matter how/when this script finishes evaluating.
window.setActiveTab = setActiveTab;

const MOBILE_QUERY = "(max-width: 880px)";
function isMobileViewport() {
  return window.matchMedia(MOBILE_QUERY).matches;
}

function closeMobileDrawer() {
  const layout = document.getElementById("adminLayout");
  if (!layout) return;
  layout.classList.remove("mobile-open");
  const mobileBtn = document.getElementById("mobileNavToggle");
  if (mobileBtn) mobileBtn.setAttribute("aria-expanded", "false");
}

function initSidebarChrome() {
  // Desktop rail collapse / mobile drawer open — same button, two behaviors.
  const sidebarToggleBtn = document.getElementById("sidebarToggle");
  if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener("click", () => {
      const layout = document.getElementById("adminLayout");

      if (isMobileViewport()) {
        const open = layout.classList.toggle("mobile-open");
        sidebarToggleBtn.setAttribute("aria-expanded", String(open));
        sidebarToggleBtn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
        return;
      }

      layout.classList.toggle("collapsed");
      const collapsed = layout.classList.contains("collapsed");
      sidebarToggleBtn.setAttribute("aria-expanded", String(!collapsed));
      sidebarToggleBtn.setAttribute("aria-label", collapsed ? "Open sidebar" : "Collapse sidebar");
      sidebarToggleBtn.title = collapsed ? "Open sidebar" : "Collapse sidebar";
    });
  }

  // Hamburger button in the topbar (mobile only)
  const mobileBtn = document.getElementById("mobileNavToggle");
  if (mobileBtn) {
    mobileBtn.addEventListener("click", () => {
      const layout = document.getElementById("adminLayout");
      const open = layout.classList.toggle("mobile-open");
      mobileBtn.setAttribute("aria-expanded", String(open));
    });
  }

  // Tapping the dimmed backdrop closes the drawer
  const backdrop = document.getElementById("sidebarBackdrop");
  if (backdrop) backdrop.addEventListener("click", closeMobileDrawer);

  // Keep state sane when crossing the mobile/desktop breakpoint
  const mq = window.matchMedia(MOBILE_QUERY);
  if (mq && mq.addEventListener) {
    mq.addEventListener("change", () => {
      const layout = document.getElementById("adminLayout");
      layout.classList.remove("mobile-open", "collapsed");
      const toggleBtn = document.getElementById("sidebarToggle");
      toggleBtn.setAttribute("aria-expanded", "true");
      toggleBtn.setAttribute("aria-label", "Collapse sidebar");
      toggleBtn.title = "Collapse sidebar";
    });
  }
}

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("adminUsername").value.trim(); // actually email now
  const password = document.getElementById("adminPassword").value;

  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });

    if (!res.ok) {
      throw new Error("Incorrect credentials");
    }

    const data = await res.json();
    sessionStorage.setItem(AUTH_KEY, `Bearer ${data.access_token}`);
    sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));

    // Also set roles/permissions from /me to be safe
    const me = await adminApi("/auth/me");
    sessionStorage.setItem('ROLES', JSON.stringify([me.role]));
    sessionStorage.setItem('PERMISSIONS', JSON.stringify(me.permissions || []));

    showDashboard();
  } catch (err) {
    clearAuth();
    const box = document.getElementById("loginError");
    box.textContent = "Incorrect username or password.";
    box.hidden = false;
  }
});

document.getElementById("logoutBtn").addEventListener("click", () => {
  clearAuth();
  showLogin();
});

["statusModal", "postConsultationChoiceModal"].forEach((id) => {
  const modal = document.getElementById(id);
  if (!modal) return;

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.hidden = true;
    }
  });
});

document.querySelectorAll("[data-close-status-modal]").forEach((btn) => {
  btn.addEventListener("click", () => hideStatusModal());
});

document.querySelectorAll("[data-close-choice-modal]").forEach((btn) => {
  btn.addEventListener("click", () => hidePostConsultationChoiceModal());
});

document.getElementById("choiceAddPrescriptionBtn")?.addEventListener("click", () => {
  hidePostConsultationChoiceModal();
  openPrescriptionModal(adminState.selectedAppointmentCode);
});

document.getElementById("choiceAddReportBtn")?.addEventListener("click", () => {
  hidePostConsultationChoiceModal();
  openMedicalReportModal(adminState.selectedAppointmentCode);
});

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

async function loadStats() {
  const grid = document.getElementById("statGrid");
  try {
    const s = await adminApi("/admin/stats");
    grid.innerHTML = `
      <div class="stat-card accent">
        <div class="stat-label">Active bookings</div>
        <div class="stat-value">${s.active_bookings}</div>
      </div>
      <div class="stat-card mint">
        <div class="stat-label">Today's bookings</div>
        <div class="stat-value">${s.today_bookings}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Cancelled</div>
        <div class="stat-value">${s.cancelled_bookings}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">All-time total</div>
        <div class="stat-value">${s.total_appointments}</div>
      </div>
    `;
    renderBreakdown("byBranch", s.by_branch, "branch");
    renderBreakdown("byDepartment", s.by_department, "department");
    renderBreakdown(
      "topDoctors",
      s.top_doctors.map((d) => ({ label: `${d.doctor} (${d.branch})`, count: d.count })),
      null
    );
  } catch (err) {
    if (err.message !== "Unauthorized") {
      grid.innerHTML = `<div class="empty-note">Couldn't load stats: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderBreakdown(containerId, rows, labelKey) {
  const el = document.getElementById(containerId);
  if (!rows || !rows.length) {
    el.innerHTML = `<div class="breakdown-empty">No bookings yet.</div>`;
    return;
  }
  el.innerHTML = rows
    .map((r) => {
      const label = labelKey ? r[labelKey] : r.label;
      return `<div class="breakdown-row"><span>${escapeHtml(label)}</span><span class="count">${r.count}</span></div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Filter dropdown options (public endpoints — no auth needed for these)
// ---------------------------------------------------------------------------

function populateBranchDropdowns(branches) {
  const branchSel = document.getElementById("fBranch");
  if (branchSel) {
    branchSel.innerHTML = `<option value="">All branches</option>`;
    branches.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b.id;
      opt.textContent = b.name;
      branchSel.appendChild(opt);
    });
  }

  const doctorBranchSelect = document.getElementById("doctorBranch");
  if (doctorBranchSelect) {
    doctorBranchSelect.innerHTML = branches
      .map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`)
      .join("");
  }
}

async function loadAdminLookupData() {
  try {
    const [branches, departments] = await Promise.all([
      adminApi("/admin/branches"),
      publicApi("/departments/all"),
    ]);
    adminState.branches = branches;
    adminState.departments = departments;

    populateBranchDropdowns(branches);

    const deptSel = document.getElementById("fDepartment");
    if (deptSel) {
      deptSel.innerHTML = `<option value="">All departments</option>`;
      departments.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.id;
        opt.textContent = d.name;
        deptSel.appendChild(opt);
      });
    }

    const doctorDeptSelect = document.getElementById("doctorDepartment");
    if (doctorDeptSelect) {
      doctorDeptSelect.innerHTML = departments
        .map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`)
        .join("");
    }

    const branchStatusSelect = document.getElementById("branchStatus");
    if (branchStatusSelect) branchStatusSelect.value = "OPEN";
  } catch (err) {
    console.warn("Couldn't load admin lookup data:", err.message);
  }
}

// ---------------------------------------------------------------------------
// Bookings table
// ---------------------------------------------------------------------------

function buildQuery() {
  const params = new URLSearchParams();
  const f = state.filters;
  if (f.search) params.set("search", f.search);
  if (f.status) params.set("status", f.status);
  if (f.branch_id) params.set("branch_id", f.branch_id);
  if (f.department_id) params.set("department_id", f.department_id);
  if (f.date_from) params.set("date_from", f.date_from);
  if (f.date_to) params.set("date_to", f.date_to);
  params.set("limit", PAGE_SIZE);
  params.set("offset", state.offset);
  return params.toString();
}

async function loadBookings() {
  const tbody = document.getElementById("tableBody");
  tbody.innerHTML = `<tr><td colspan="11" class="loading">Loading bookings&hellip;</td></tr>`;
  try {
    const data = await adminApi(`/admin/appointments?${buildQuery()}`);
    state.total = data.total;
    renderTable(data.appointments);
    renderPagination();
  } catch (err) {
    if (err.message !== "Unauthorized") {
      tbody.innerHTML = `<tr><td colspan="11" class="empty-note">Couldn't load bookings: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

function renderTable(rows) {
  const tbody = document.getElementById("tableBody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="12" class="empty-note">No bookings match these filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((r) => `
      <tr>
        <td class="code-cell">${escapeHtml(r.appointment_code)}</td>
        <td>${escapeHtml(r.patient_name)}</td>
        <td>${escapeHtml(r.mobile)}</td>
        <td>${escapeHtml(r.branch_name)}</td>
        <td>${escapeHtml(r.department_name)}</td>
        <td>${escapeHtml(r.doctor_name)}</td>
        <td>${escapeHtml(r.appointment_date)}</td>
        <td>${formatTime(r.time_slot)}</td>

        <td><span class="status-pill ${r.status}">${r.status}</span></td>
        <td>
          ${r.status === "BOOKED" || r.status === "CONFIRMED" || r.status === "RESCHEDULED"
            ? `<button class="complete-btn" data-code="${escapeHtml(r.appointment_code)}" title="Mark as completed">✓ Complete</button>`
            : ""}
          ${r.status === "BOOKED"
            ? `<button class="cancel-btn" data-code="${escapeHtml(r.appointment_code)}">Cancel</button>`
            : ""}
        </td>
      </tr>
    `)
    .join("");

  tbody.querySelectorAll(".cancel-btn").forEach((btn) => {
    btn.addEventListener("click", () => cancelBooking(btn.dataset.code, btn));
  });

  tbody.querySelectorAll(".complete-btn").forEach((btn) => {
    btn.addEventListener("click", () => openCompleteModal(btn.dataset.code));
  });
}

function showStatusModal(title, message) {
  const modal = document.getElementById("statusModal");
  const titleEl = document.getElementById("statusModalTitle");
  const textEl = document.getElementById("statusModalText");
  if (!modal || !titleEl || !textEl) return;

  titleEl.textContent = title;
  textEl.textContent = message;
  modal.hidden = false;
}

function hideStatusModal() {
  const modal = document.getElementById("statusModal");
  if (modal) modal.hidden = true;
}

function showPostConsultationChoiceModal() {
  const modal = document.getElementById("postConsultationChoiceModal");
  if (modal) modal.hidden = false;
}

function hidePostConsultationChoiceModal() {
  const modal = document.getElementById("postConsultationChoiceModal");
  if (modal) modal.hidden = true;
}

function openCompleteModal(appointmentCode) {
  adminState.selectedAppointmentCode = appointmentCode;
  document.getElementById("completeAppointmentModal").hidden = false;
  document.getElementById("completeForm").reset();
}

async function cancelBooking(code, btnEl) {
  if (!confirm(`Cancel appointment ${code}? This frees the slot for other patients.`)) return;
  btnEl.disabled = true;
  btnEl.textContent = "Cancelling\u2026";
  try {
    await adminApi(`/admin/appointments/${code}/cancel`, { method: "POST" });
    loadBookings();
    loadStats();
  } catch (err) {
    if (err.message !== "Unauthorized") {
      alert(`Couldn't cancel: ${err.message}`);
      btnEl.disabled = false;
      btnEl.textContent = "Cancel";
    }
  }
}

async function submitCompleteAppointment(e) {
  e.preventDefault();
  const code = adminState.selectedAppointmentCode;
  const symptoms = document.getElementById("symptoms").value.trim();
  const diagnosis = document.getElementById("diagnosis").value.trim();
  const notes = document.getElementById("consultationNotes").value.trim();

  if (!symptoms || !diagnosis) {
    showStatusModal("Missing information", "Please fill in both symptoms and diagnosis before marking the appointment complete.");
    return;
  }

  try {
    await adminApi(`/admin/appointments/${code}/complete`, {
      method: "POST",
      body: JSON.stringify({ symptoms, diagnosis, notes }),
    });

    document.getElementById("completeAppointmentModal").hidden = true;
    showPostConsultationChoiceModal();
    loadBookings();
    loadStats();
  } catch (err) {
    showStatusModal("Completion failed", err.message || "Unable to complete the appointment.");
  }
}

function showPostConsultationOptions(appointmentCode) {
  adminState.selectedAppointmentCode = appointmentCode;
  showPostConsultationChoiceModal();
}

function openPrescriptionModal(appointmentCode) {
  adminState.selectedAppointmentCode = appointmentCode;
  document.getElementById("prescriptionModal").hidden = false;
  document.getElementById("prescriptionForm").reset();
  document.getElementById("medicinesContainer").innerHTML = `
    <div class="medicine-item">
      <input type="text" class="medicine-name" placeholder="Medicine Name" required>
      <input type="text" class="medicine-dosage" placeholder="Dosage (e.g., 500mg)" required>
      <input type="text" class="medicine-frequency" placeholder="Frequency (e.g., twice daily)">
      <button type="button" class="remove-medicine-btn">Remove</button>
    </div>
  `;
  setupMedicineButtons();
}

function openMedicalReportModal(appointmentCode) {
  adminState.selectedAppointmentCode = appointmentCode;
  document.getElementById("medicalReportModal").hidden = false;
  document.getElementById("medicalReportForm").reset();
}

function setupMedicineButtons() {
  document.querySelectorAll(".remove-medicine-btn").forEach((btn) => {
    btn.addEventListener("click", () => btn.parentElement.remove());
  });
}

function addMedicineRow() {
  const container = document.getElementById("medicinesContainer");
  const newRow = document.createElement("div");
  newRow.className = "medicine-item";
  newRow.innerHTML = `
    <input type="text" class="medicine-name" placeholder="Medicine Name" required>
    <input type="text" class="medicine-dosage" placeholder="Dosage (e.g., 500mg)" required>
    <input type="text" class="medicine-frequency" placeholder="Frequency (e.g., twice daily)">
    <button type="button" class="remove-medicine-btn">Remove</button>
  `;
  container.appendChild(newRow);
  setupMedicineButtons();
}

async function submitPrescription(e) {
  e.preventDefault();
  const code = adminState.selectedAppointmentCode;
  const instructions = document.getElementById("prescriptionInstructions").value.trim();
  const validityDays = parseInt(document.getElementById("validityDays").value) || 30;

  const medicines = [];
  document.querySelectorAll(".medicine-item").forEach((item) => {
    const name = item.querySelector(".medicine-name").value.trim();
    const dosage = item.querySelector(".medicine-dosage").value.trim();
    const frequency = item.querySelector(".medicine-frequency").value.trim();
    if (name && dosage) {
      medicines.push({ name, dosage, frequency });
    }
  });

  if (medicines.length === 0) {
    showStatusModal("Prescription incomplete", "Please add at least one medicine before saving the prescription.");
    return;
  }

  try {
    await adminApi("/admin/prescriptions", {
      method: "POST",
      body: JSON.stringify({
        appointment_code: code,
        medicines,
        instructions,
        validity_days: validityDays,
      }),
    });

    document.getElementById("prescriptionModal").hidden = true;
    hidePostConsultationChoiceModal();
    showStatusModal("Prescription saved", "The prescription has been added and will appear in the patient portal.");
    loadBookings();
  } catch (err) {
    showStatusModal("Prescription failed", err.message || "Could not save the prescription.");
  }
}

async function submitMedicalReport(e) {
  e.preventDefault();
  const code = adminState.selectedAppointmentCode;
  const reportName = document.getElementById("reportName").value.trim();
  const reportType = document.getElementById("reportType").value.trim();
  const findings = document.getElementById("reportFindings").value.trim();
  const status = document.getElementById("reportStatus").value;

  if (!reportName || !reportType) {
    showStatusModal("Report incomplete", "Please fill in the report name and type before saving.");
    return;
  }

  try {
    await adminApi("/admin/medical-reports", {
      method: "POST",
      body: JSON.stringify({
        appointment_code: code,
        report_name: reportName,
        report_type: reportType,
        findings,
        status,
      }),
    });

    document.getElementById("medicalReportModal").hidden = true;
    hidePostConsultationChoiceModal();
    showStatusModal("Report saved", "The medical report has been added and will be visible in the patient portal.");
    loadBookings();
  } catch (err) {
    showStatusModal("Report failed", err.message || "Could not save the medical report.");
  }
}


function renderPagination() {
  const info = document.getElementById("pageInfo");
  const shown = state.total === 0 ? 0 : state.offset + 1;
  const shownEnd = Math.min(state.offset + PAGE_SIZE, state.total);
  info.textContent = `${shown}\u2013${shownEnd} of ${state.total}`;
  document.getElementById("prevPage").disabled = state.offset === 0;
  document.getElementById("nextPage").disabled = state.offset + PAGE_SIZE >= state.total;
}

document.getElementById("prevPage").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - PAGE_SIZE);
  loadBookings();
});
document.getElementById("nextPage").addEventListener("click", () => {
  state.offset += PAGE_SIZE;
  loadBookings();
});

["fSearch", "fStatus", "fBranch", "fDepartment", "fDateFrom", "fDateTo"].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener(el.type === "text" ? "input" : "change", () => {
      state.filters = {
        search: document.getElementById("fSearch").value.trim(),
        status: document.getElementById("fStatus").value,
        branch_id: document.getElementById("fBranch").value,
        department_id: document.getElementById("fDepartment").value,
        date_from: document.getElementById("fDateFrom").value,
        date_to: document.getElementById("fDateTo").value,
      };
      state.offset = 0;
      loadBookings();
    });
  }
});

// ---------------------------------------------------------------------------
// Doctor management (list + add/edit/delete)
// ---------------------------------------------------------------------------

function doctorRowHtml(doc) {
  return `
    <tr>
      <td>${escapeHtml(doc.name)}</td>
      <td><span class="status-pill ${doc.doctor_type}">${escapeHtml(doc.doctor_type)}</span></td>
      <td>${escapeHtml(doc.branch_name)}</td>
      <td>${escapeHtml(doc.department_name)}</td>
      <td>${escapeHtml(doc.qualification)}</td>

      <td><span class="status-pill ${doc.doctor_status}">${doc.doctor_status}</span></td>
      <td>
        <button class="btn btn-ghost btn-small edit-doctor" data-id="${doc.id}">Edit</button>
        <button class="btn btn-ghost btn-small schedule-doctor" data-id="${doc.id}" data-name="${escapeHtml(doc.name)}">Schedule</button>
        <button class="btn btn-ghost btn-small delete-doctor" data-id="${doc.id}">Delete</button>
      </td>
    </tr>
  `;
}

function wireDoctorRowActions(tbody, doctors, afterChange) {
  tbody.querySelectorAll(".edit-doctor").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const doctor = doctors.find((d) => String(d.id) === String(btn.dataset.id));
      if (!doctor) { alert("Doctor not found."); return; }
      if (!adminState.branches.length || !adminState.departments.length) {
        await loadAdminLookupData();
      }
      adminState.doctorEditId = doctor.id;
      document.getElementById("doctorFormTitle").textContent = "Edit doctor";
      document.getElementById("doctorName").value = doctor.name;
      document.getElementById("doctorBranch").value = doctor.branch_id;
      document.getElementById("doctorDepartment").value = doctor.department_id;
      document.getElementById("doctorQualification").value = doctor.qualification;
      document.getElementById("doctorCode").value = doctor.doctor_code || "";
      document.getElementById("doctorMobile").value = doctor.mobile || "";
      document.getElementById("doctorEmail").value = doctor.email || "";
      document.getElementById("doctorType").value = doctor.doctor_type || "REGULAR";
      document.getElementById("doctorDuration").value = doctor.consultation_duration || 30;

      document.getElementById("doctorStatus").value = doctor.doctor_status;
      document.getElementById("saveDoctorButton").textContent = "Update doctor";
      document.getElementById("cancelDoctorEdit").hidden = false;
      showDoctorForm(true);
    });
  });

  tbody.querySelectorAll(".schedule-doctor").forEach((btn) => {
    btn.addEventListener("click", () => {
      openScheduleModal(btn.dataset.id, btn.dataset.name);
    });
  });

  tbody.querySelectorAll(".delete-doctor").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this doctor? This cannot be undone.")) return;
      btn.disabled = true;
      const originalLabel = btn.textContent;
      btn.textContent = "Deleting\u2026";
      try {
        await adminApi(`/admin/doctors/${btn.dataset.id}`, { method: "DELETE" });
        if (afterChange) await afterChange();
      } catch (err) {
        if (err.message !== "Unauthorized") {
          alert(`Couldn't delete doctor: ${err.message}`);
          btn.disabled = false;
          btn.textContent = originalLabel;
        }
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Schedule Management
// ---------------------------------------------------------------------------
let currentScheduleDoctorId = null;

async function openScheduleModal(doctorId, doctorName) {
  currentScheduleDoctorId = doctorId;
  document.getElementById("scheduleDoctorName").textContent = doctorName;
  await loadDoctorSchedule();
  document.getElementById("doctorScheduleModal").hidden = false;
}

document.getElementById("closeDoctorScheduleModal").addEventListener("click", () => {
  document.getElementById("doctorScheduleModal").hidden = true;
});

async function loadDoctorSchedule() {
  const weeklyTbody = document.getElementById("weeklyScheduleTableBody");
  const specialTbody = document.getElementById("specialAvailabilityTableBody");
  weeklyTbody.innerHTML = `<tr><td colspan="4" class="loading">Loading...</td></tr>`;
  specialTbody.innerHTML = `<tr><td colspan="4" class="loading">Loading...</td></tr>`;

  try {
    const data = await adminApi(`/doctors/${currentScheduleDoctorId}/availability`);

    // Weekly Schedule
    const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    if (data.schedule && data.schedule.length > 0) {
      weeklyTbody.innerHTML = data.schedule.map(s => `
        <tr>
          <td>${escapeHtml(DAY_NAMES[s.day_of_week] || s.day_of_week)}</td>
          <td>${s.start_time}</td>
          <td>${s.end_time}</td>
          <td><button class="btn btn-ghost btn-small delete-weekly-sched" data-id="${s.id}">Delete</button></td>
        </tr>
      `).join("");

      weeklyTbody.querySelectorAll(".delete-weekly-sched").forEach(btn => {
        btn.addEventListener("click", async () => {
          if (!confirm("Remove this weekly schedule?")) return;
          try {
            await adminApi(`/doctors/${currentScheduleDoctorId}/schedule/${btn.dataset.id}`, { method: "DELETE" });
            loadDoctorSchedule();
          } catch (e) { alert(e.message); }
        });
      });
    } else {
      weeklyTbody.innerHTML = `<tr><td colspan="4" class="empty-note">No regular schedule set.</td></tr>`;
    }

    // Special Availability
    if (data.special_availability && data.special_availability.length > 0) {
      specialTbody.innerHTML = data.special_availability.map(s => `
        <tr>
          <td>${s.available_date}</td>
          <td>${s.is_blocked ? '-' : s.start_time + ' - ' + s.end_time}</td>
          <td><span class="status-pill ${s.is_blocked ? 'INACTIVE' : 'ACTIVE'}">${s.is_blocked ? 'Blocked' : 'Available'}</span></td>
          <td><button class="btn btn-ghost btn-small delete-special-sched" data-id="${s.id}">Delete</button></td>
        </tr>
      `).join("");

      specialTbody.querySelectorAll(".delete-special-sched").forEach(btn => {
        btn.addEventListener("click", async () => {
          if (!confirm("Remove this special availability?")) return;
          try {
            await adminApi(`/doctors/${currentScheduleDoctorId}/special-availability/${btn.dataset.id}`, { method: "DELETE" });
            loadDoctorSchedule();
          } catch (e) { alert(e.message); }
        });
      });
    } else {
      specialTbody.innerHTML = `<tr><td colspan="4" class="empty-note">No special availability set.</td></tr>`;
    }

  } catch (err) {
    if (err.message !== "Unauthorized") alert(`Error loading schedule: ${err.message}`);
  }
}

document.getElementById("addWeeklyScheduleForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const day = parseInt(document.getElementById("schedDayOfWeek").value, 10);
  const start = document.getElementById("schedStartTime").value;
  const end = document.getElementById("schedEndTime").value;
  try {
    await adminApi(`/doctors/${currentScheduleDoctorId}/schedule`, {
      method: "POST",
      body: JSON.stringify({ day_of_week: day, start_time: start, end_time: end })
    });
    document.getElementById("addWeeklyScheduleForm").reset();
    loadDoctorSchedule();
  } catch (err) { alert(`Error: ${err.message}`); }
});

document.getElementById("addSpecialAvailabilityForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const date = document.getElementById("specialDate").value;
  const isBlocked = document.getElementById("specialIsBlocked").checked;
  const start = document.getElementById("specialStartTime").value || "00:00";
  const end = document.getElementById("specialEndTime").value || "00:00";

  try {
    await adminApi(`/doctors/${currentScheduleDoctorId}/special-availability`, {
      method: "POST",
      body: JSON.stringify({ available_date: date, start_time: start, end_time: end, is_blocked: isBlocked })
    });
    document.getElementById("addSpecialAvailabilityForm").reset();
    loadDoctorSchedule();
  } catch (err) { alert(`Error: ${err.message}`); }
});

async function loadDoctorManagement() {
  if (!adminState.branches.length || !adminState.departments.length) {
    await loadAdminLookupData();
  }

  const tbody = document.getElementById("doctorTableBody");
  tbody.innerHTML = `<tr><td colspan="7" class="loading">Loading doctors&hellip;</td></tr>`;
  try {
    const doctors = await adminApi("/admin/doctors");
    if (!doctors.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-note">No doctors found.</td></tr>`;
      return;
    }
    tbody.innerHTML = doctors.map(doctorRowHtml).join("");
    wireDoctorRowActions(tbody, doctors, async () => {
      await loadDoctorManagement();
      await loadBranches();
    });
  } catch (err) {
    if (err.message !== "Unauthorized") {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-note">Couldn't load doctors: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Branch management (list + add/edit/delete, plus doctors-by-branch view)
// ---------------------------------------------------------------------------

async function loadBranches() {
  const sel = document.getElementById("branchSelect");
  sel.innerHTML = `<option value="">Loading branches&hellip;</option>`;
  try {
    const branches = await adminApi("/admin/branches");
    adminState.branches = branches;

    if (!branches.length) {
      sel.innerHTML = `<option value="">No branches found</option>`;
      document.getElementById("branchDoctorTableBody").innerHTML = `<tr><td colspan="8" class="empty-note">No branches available.</td></tr>`;
      document.getElementById("branchTableBody").innerHTML = `<tr><td colspan="5" class="empty-note">No branches available.</td></tr>`;
      return;
    }

    sel.innerHTML = branches.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join("");
    sel.onchange = async () => {
      const id = sel.value;
      if (id) await loadBranchDoctors(id);
      else document.getElementById("branchDoctorTableBody").innerHTML = `<tr><td colspan="8" class="empty-note">Select a branch to load doctors.</td></tr>`;
    };

    renderBranchList(branches);

    const firstId = branches[0].id;
    sel.value = firstId;
    await loadBranchDoctors(firstId);
  } catch (err) {
    if (err.message !== "Unauthorized") {
      sel.innerHTML = `<option value="">Couldn't load branches</option>`;
      document.getElementById("branchDoctorTableBody").innerHTML = `<tr><td colspan="8" class="empty-note">Couldn't load branches: ${escapeHtml(err.message)}</td></tr>`;
      document.getElementById("branchTableBody").innerHTML = `<tr><td colspan="5" class="empty-note">Couldn't load branches: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

function renderBranchList(branches) {
  const tbody = document.getElementById("branchTableBody");
  tbody.innerHTML = branches
    .map((b) => `
      <tr>
        <td>${escapeHtml(b.name)}</td>
        <td>${escapeHtml(b.address)}</td>
        <td>${escapeHtml(b.phone)}</td>
        <td><span class="status-pill ${b.branch_status}">${b.branch_status}</span></td>
        <td>
          <button class="btn btn-ghost btn-small edit-branch" data-id="${b.id}">Edit</button>
          <button class="btn btn-ghost btn-small delete-branch" data-id="${b.id}">Delete</button>
        </td>
      </tr>
    `)
    .join("");

  tbody.querySelectorAll(".edit-branch").forEach((btn) => {
    btn.addEventListener("click", () => {
      const branch = adminState.branches.find((b) => String(b.id) === String(btn.dataset.id));
      if (!branch) { alert("Branch not found."); return; }
      adminState.branchEditId = branch.id;
      document.getElementById("branchFormTitle").textContent = "Edit branch";
      document.getElementById("branchName").value = branch.name;
      document.getElementById("branchAddress").value = branch.address;
      document.getElementById("branchPhone").value = branch.phone;
      document.getElementById("branchStatus").value = branch.branch_status;
      document.getElementById("saveBranchButton").textContent = "Update branch";
      document.getElementById("cancelBranchEdit").hidden = false;
      showBranchForm(true);
    });
  });

  tbody.querySelectorAll(".delete-branch").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this branch? It must have no doctors or appointments.")) return;
      try {
        await adminApi(`/admin/branches/${btn.dataset.id}`, { method: "DELETE" });
        await loadBranches();
        await loadDoctorManagement();
      } catch (err) {
        alert(`Couldn't delete branch: ${err.message}`);
      }
    });
  });
}

async function loadBranchDoctors(branchId) {
  const tbody = document.getElementById("branchDoctorTableBody");
  tbody.innerHTML = `<tr><td colspan="8" class="loading">Loading doctors&hellip;</td></tr>`;
  try {
    const allDocs = await adminApi("/admin/doctors");
    const docs = allDocs.filter((d) => String(d.branch_id) === String(branchId));
    if (!docs.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-note">No doctors found for this branch.</td></tr>`;
      return;
    }
    tbody.innerHTML = docs.map(doctorRowHtml).join("");
    wireDoctorRowActions(tbody, docs, async () => {
      await loadBranchDoctors(branchId);
      await loadDoctorManagement();
    });
  } catch (err) {
    if (err.message !== "Unauthorized") {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-note">Couldn't load doctors: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Doctor / branch forms
// ---------------------------------------------------------------------------

function resetDoctorForm() {
  adminState.doctorEditId = null;
  document.getElementById("doctorFormTitle").textContent = "Add new doctor";
  document.getElementById("doctorForm").reset();
  document.getElementById("saveDoctorButton").textContent = "Save doctor";
  document.getElementById("cancelDoctorEdit").hidden = true;
}

function resetBranchForm() {
  adminState.branchEditId = null;
  document.getElementById("branchFormTitle").textContent = "Add new branch";
  document.getElementById("branchForm").reset();
  document.getElementById("saveBranchButton").textContent = "Save branch";
  document.getElementById("cancelBranchEdit").hidden = true;
}

async function openAddDoctorForm() {
  if (!adminState.branches.length || !adminState.departments.length) {
    await loadAdminLookupData();
  }
  resetDoctorForm();
  showDoctorForm(true);
}

function openAddBranchForm() {
  resetBranchForm();
  showBranchForm(true);
}

async function submitDoctorForm(event) {
  event.preventDefault();
  const form = event.target;
  const data = {
    doctor_code: form.doctor_code.value.trim() || null,
    name: form.name.value.trim(),
    branch_id: Number(form.branch_id.value),
    department_id: Number(form.department_id.value),
    qualification: form.qualification.value.trim(),

    doctor_status: form.doctor_status.value,
    mobile: form.mobile.value.trim() || null,
    email: form.email.value.trim() || null,
    specialization: form.qualification.value.trim(),
    doctor_type: form.doctor_type.value,
    consultation_duration: Number(form.consultation_duration.value),
  };
  try {
    const method = adminState.doctorEditId ? "PUT" : "POST";
    const url = adminState.doctorEditId ? `/admin/doctors/${adminState.doctorEditId}` : "/admin/doctors";
    await adminApi(url, { method, body: JSON.stringify(data) });
    const isEditing = Boolean(adminState.doctorEditId);
    await loadDoctorManagement();
    await loadBranches();
    if (isEditing) {
      document.getElementById("saveDoctorButton").textContent = "Saved";
      setTimeout(() => {
        resetDoctorForm();
        showDoctorForm(false);
      }, 600);
      return;
    }
    resetDoctorForm();
    showDoctorForm(false);
  } catch (err) {
    alert(`Couldn't save doctor: ${err.message}`);
  }
}

async function submitBranchForm(event) {
  event.preventDefault();
  const form = event.target;
  const data = {
    name: form.name.value.trim(),
    address: form.address.value.trim(),
    phone: form.phone.value.trim(),
    branch_status: form.branch_status.value,
  };
  try {
    const method = adminState.branchEditId ? "PUT" : "POST";
    const url = adminState.branchEditId ? `/admin/branches/${adminState.branchEditId}` : "/admin/branches";
    await adminApi(url, { method, body: JSON.stringify(data) });
    const isEditing = Boolean(adminState.branchEditId);
    await loadBranches();
    await loadDoctorManagement();
    if (isEditing) {
      document.getElementById("saveBranchButton").textContent = "Saved";
      setTimeout(() => {
        resetBranchForm();
        showBranchForm(false);
      }, 600);
      return;
    }
    resetBranchForm();
    showBranchForm(false);
  } catch (err) {
    alert(`Couldn't save branch: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Patients management
// ---------------------------------------------------------------------------
async function loadPatients() {
  const tbody = document.getElementById("patientTableBody");
  tbody.innerHTML = `<tr><td colspan="6" class="loading">Loading patients...</td></tr>`;
  try {
    const patients = await adminApi("/admin/patients");
    adminState.patients = patients;

    if (!patients.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-note">No patients found.</td></tr>`;
      return;
    }

    tbody.innerHTML = patients.map(p => `
      <tr>
        <td class="code-cell">${escapeHtml(p.patient_id)}</td>
        <td>${escapeHtml(p.full_name)}</td>
        <td>${escapeHtml(p.mobile)}</td>
        <td>${escapeHtml(p.gender)}</td>
        <td>${escapeHtml(p.dob)}</td>
        <td>
          <button class="btn btn-ghost btn-small" data-action="view" data-id="${p.id}">View Details & History</button>
          <button class="btn btn-ghost btn-small" data-action="edit" data-id="${p.id}">Edit</button>
          <button class="btn btn-ghost btn-small" data-action="delete" data-id="${p.id}">Delete</button>
        </td>
      </tr>
    `).join("");

    tbody.querySelectorAll("[data-action]").forEach((btn) => {
      const id = Number(btn.dataset.id);
      btn.addEventListener("click", async () => {
        if (btn.dataset.action === "view") {
          await viewPatientDetails(id);
        } else if (btn.dataset.action === "edit") {
          openPatientEditForm(id);
        } else if (btn.dataset.action === "delete") {
          if (!confirm("Delete this patient record?")) return;
          try {
            await adminApi(`/admin/patients/${id}`, { method: "DELETE" });
            await loadPatients();
          } catch (err) {
            if (err.message !== "Unauthorized") {
              alert(`Couldn't delete patient: ${err.message}`);
            }
          }
        }
      });
    });
  } catch (err) {
    if (err.message !== "Unauthorized") {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-note">Couldn't load patients: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

async function downloadPatientExport(format) {
  const res = await fetch(`${API_BASE}/admin/patients/export?format=${format}`, {
    headers: { Authorization: getAuthHeader() || "" },
  });
  if (!res.ok) { alert("Couldn't export patients."); return; }
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url; link.download = `patients.${format}`; link.click();
  URL.revokeObjectURL(url);
}

async function importPatientsPreview(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const res = await fetch(`${API_BASE}/admin/patients/import/preview?filename=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { Authorization: getAuthHeader() || "", "Content-Type": "application/octet-stream" }, body: file,
    });
    const preview = await res.json();
    if (!res.ok) throw new Error(preview.detail || "Unable to validate file");
    const errors = preview.errors.slice(0, 5).map((e) => `Row ${e.row}: ${e.error}`).join("\n");
    if (!confirm(`${preview.total} records: ${preview.valid} valid, ${preview.invalid} invalid.\n${errors}\n\nImport valid records?`)) return;
    const result = await adminApi("/admin/patients/import/commit", { method: "POST", body: JSON.stringify({ token: preview.token }) });
    alert(`Import complete: ${result.created} created, ${result.updated} updated.`);
    await loadPatients();
  } catch (err) {
    alert(`Couldn't import patients: ${err.message}`);
  } finally {
    event.target.value = "";
  }
}

function resetPatientForm() {
  adminState.patientEditId = null;
  document.getElementById("patientFormModal").reset();
  document.getElementById("patientFormTitle").textContent = "Edit patient";
  document.getElementById("savePatientButton").textContent = "Update patient";
}

function openPatientEditForm(id) {
  const patient = adminState.patients.find((x) => x.id === id);
  if (!patient) return;
  adminState.patientEditId = id;
  document.getElementById("patientFormTitle").textContent = "Edit patient";
  const form = document.getElementById("patientFormModal");
  form.full_name.value = patient.full_name || "";
  form.dob.value = patient.dob || "";
  form.gender.value = patient.gender || "Other";
  form.mobile.value = patient.mobile || "";
  form.email.value = patient.email || "";
  form.address.value = patient.address || "";
  form.emergency_contact.value = patient.emergency_contact || "";
  form.blood_group.value = patient.blood_group || "";
  form.allergies.value = patient.allergies || "";
  form.medical_history.value = patient.medical_history || "";
  document.getElementById("savePatientButton").textContent = "Update patient";
  document.getElementById("patientModal").hidden = false;
}

async function submitPatientForm(event) {
  event.preventDefault();
  const form = event.target;
  const data = {
    full_name: form.full_name.value.trim(),
    dob: form.dob.value,
    gender: form.gender.value,
    mobile: form.mobile.value.trim(),
    email: form.email.value.trim() || null,
    address: form.address.value.trim(),
    emergency_contact: form.emergency_contact.value.trim() || null,
    blood_group: form.blood_group.value.trim() || null,
    allergies: form.allergies.value.trim() || null,
    medical_history: form.medical_history.value.trim() || null,
  };

  try {
    await adminApi(`/admin/patients/${adminState.patientEditId}`, {
      method: "PUT",
      body: JSON.stringify(data)
    });
    document.getElementById("patientModal").hidden = true;
    await loadPatients();
  } catch (err) {
    alert(`Couldn't save patient: ${err.message}`);
  }
}

window.viewPatientDetails = async function(id) {
  const p = adminState.patients.find(x => x.id === id);
  if (!p) return;

  const profileDiv = document.getElementById("patientDetailsProfile");
  const timelineDiv = document.getElementById("patientDetailsTimeline");

  profileDiv.innerHTML = `
    <div style="display:flex; gap: 20px; align-items: start; flex-wrap: wrap;">
      <div style="flex:1; min-width: 250px;">
        <h3 style="margin:0;">${escapeHtml(p.full_name)}</h3>
        <p style="color:var(--ink-soft); font-family:var(--font-mono); margin: 4px 0 10px;">${escapeHtml(p.patient_id)}</p>
        <p style="margin:4px 0;"><strong>Mobile:</strong> ${escapeHtml(p.mobile)}</p>
        <p style="margin:4px 0;"><strong>DOB:</strong> ${escapeHtml(p.dob)} | <strong>Gender:</strong> ${escapeHtml(p.gender)}</p>
        <p style="margin:4px 0;"><strong>Address:</strong> ${escapeHtml(p.address)}</p>
      </div>
      <div style="flex:1; min-width: 250px; background: var(--mist); padding: 15px; border-radius: var(--radius-sm);">
        <p style="margin:0 0 8px;"><strong>Blood Group:</strong> ${escapeHtml(p.blood_group || "N/A")}</p>
        <p style="margin:0 0 8px;"><strong>Allergies:</strong> ${escapeHtml(p.allergies || "None reported")}</p>
        <p style="margin:0;"><strong>Medical History:</strong> ${escapeHtml(p.medical_history || "None reported")}</p>
      </div>
    </div>
  `;

  timelineDiv.innerHTML = `<div class="loading-sm">Loading history...</div>`;
  document.getElementById("patientDetailsModal").hidden = false;

  try {
    const res = await adminApi(`/admin/patients/${id}/history`);
    const timeline = res.timeline || [];
    const consultations = res.consultations || [];
    const prescriptions = res.prescriptions || [];
    const reports = res.reports || [];

    let timelineHtml = "";
    if (timeline.length === 0) {
      timelineHtml = `<div class="empty-note" style="padding: 10px;">No treatment records or bookings found.</div>`;
    } else {
      timelineHtml = `
      <div style="padding-left: 20px; border-left: 2px solid var(--line); margin-left: 10px; padding-top: 5px;">
        ${timeline.map(event => `
          <div style="position:relative; margin-bottom: 24px;">
            <div style="position:absolute; left: -27px; top: 2px; width: 14px; height: 14px; border-radius: 50%; background: ${event.type === 'APPOINTMENT_CANCELLED' ? 'var(--coral)' : event.type === 'CONSULTATION_COMPLETED' ? 'var(--teal-mid)' : 'var(--teal)'}; border: 2px solid white;"></div>
            <div style="font-size: 12px; color: var(--ink-soft); font-family: var(--font-mono); margin-bottom:4px;">${event.date} at ${event.time}</div>
            <h5 style="margin: 0 0 4px; font-size:14px;">${escapeHtml(event.title)}</h5>
            <p style="margin: 0; font-size: 13px; color: var(--ink);">${escapeHtml(event.description)}</p>
          </div>
        `).join("")}
      </div>`;
    }

    const consultHtml = consultations.length ? consultations.map(c => `
      <div style="padding: 12px 0; border-bottom: 1px solid var(--line);">
        <div style="font-size:12px; color:var(--ink-soft); font-family:var(--font-mono); margin-bottom: 4px;">${escapeHtml(c.consultation_date)} • ${escapeHtml(c.doctor_name)}</div>
        <div><strong>Diagnosis:</strong> ${escapeHtml(c.diagnosis || "Not recorded")}</div>
        <div><strong>Symptoms:</strong> ${escapeHtml(c.symptoms || "Not recorded")}</div>
        <div><strong>Notes:</strong> ${escapeHtml(c.notes || "Not recorded")}</div>
      </div>
    `).join("") : `<div class="empty-note" style="padding: 10px;">No consultation records available.</div>`;

    const prescriptionHtml = prescriptions.length ? prescriptions.map(p => {
      const meds = Array.isArray(p.medicines) ? p.medicines : [];
      const medRows = meds.length ? meds.map(m => `
        <div style="padding:6px 0; border-bottom:1px solid var(--line);">
          <strong>${escapeHtml(m.name || "Medicine")}</strong> — ${escapeHtml(m.dosage || "")}${m.frequency ? ` • ${escapeHtml(m.frequency)}` : ""}
          ${m.instructions ? `<div style="font-size:12px; color:var(--ink-soft);">${escapeHtml(m.instructions)}</div>` : ""}
        </div>
      `).join("") : `<div style="color:var(--ink-soft);">No medicines listed.</div>`;
      return `
        <div style="padding: 12px 0; border-bottom: 1px solid var(--line);">
          <div style="font-size:12px; color:var(--ink-soft); font-family:var(--font-mono); margin-bottom: 4px;">${escapeHtml(p.prescription_date)} • Dr. ${escapeHtml(p.doctor_name)}</div>
          ${medRows}
          ${p.instructions ? `<div style="margin-top:8px;"><strong>Instructions:</strong> ${escapeHtml(p.instructions)}</div>` : ""}
        </div>
      `;
    }).join("") : `<div class="empty-note" style="padding: 10px;">No prescriptions recorded.</div>`;

    const reportHtml = reports.length ? reports.map(r => `
      <div style="padding: 12px 0; border-bottom: 1px solid var(--line);">
        <div style="font-size:12px; color:var(--ink-soft); font-family:var(--font-mono); margin-bottom: 4px;">${escapeHtml(r.report_date)} • ${escapeHtml(r.report_type)} • ${escapeHtml(r.doctor_name || "Doctor")}</div>
        <div><strong>${escapeHtml(r.report_name)}</strong></div>
        <div><strong>Status:</strong> ${escapeHtml(r.status || "N/A")}</div>
        <div><strong>Findings:</strong> ${escapeHtml(r.findings || "No findings recorded")}</div>
      </div>
    `).join("") : `<div class="empty-note" style="padding: 10px;">No medical reports recorded.</div>`;

    timelineDiv.innerHTML = `
      <div style="display:flex; flex-direction:column; gap: 26px;">
        <div>
          <h5 style="margin:0 0 10px; border-bottom:1px solid var(--line); padding-bottom:8px;">Appointment Timeline</h5>
          ${timelineHtml}
        </div>

        <div>
          <h5 style="margin:0 0 10px; border-bottom:1px solid var(--line); padding-bottom:8px;">Consultation Records</h5>
          ${consultHtml}
        </div>

        <div>
          <h5 style="margin:0 0 10px; border-bottom:1px solid var(--line); padding-bottom:8px;">Prescriptions</h5>
          ${prescriptionHtml}
        </div>

        <div>
          <h5 style="margin:0 0 10px; border-bottom:1px solid var(--line); padding-bottom:8px;">Medical Reports</h5>
          ${reportHtml}
        </div>
      </div>
    `;
  } catch (err) {
    timelineDiv.innerHTML = `<div class="empty-note">Failed to load history: ${err.message}</div>`;
  }
};

// ---------------------------------------------------------------------------
// Notification Config
// ---------------------------------------------------------------------------
async function loadNotificationConfig() {
  try {
    const config = await adminApi("/admin/config/notifications");
    document.getElementById("configTwilioSid").value = config.twilio_account_sid || "";
    document.getElementById("configTwilioAuth").value = config.twilio_auth_token || "";
    document.getElementById("configTwilioFrom").value = config.twilio_from_number || "";
    document.getElementById("configSmtpHost").value = config.smtp_host || "";
    document.getElementById("configSmtpPort").value = config.smtp_port || "";
    document.getElementById("configSmtpUser").value = config.smtp_username || "";
    document.getElementById("configSmtpPass").value = config.smtp_password || "";
    document.getElementById("configSmtpFrom").value = config.smtp_from || "";
  } catch (err) {
    console.error("Failed to load notification config:", err);
  }
}

async function loadWhatsappConfig() {
  try {
    const config = await adminApi("/admin/config/whatsapp");
    document.getElementById("configWhatsappToken").value = config.access_token || "";
    document.getElementById("configWhatsappPhoneId").value = config.phone_number_id || "";
    document.getElementById("configWhatsappBizId").value = config.business_account_id || "";
    document.getElementById("configWhatsappVerifyToken").value = config.verify_token || "";
    document.getElementById("configWhatsappApiVersion").value = config.api_version || "";
  } catch (err) {
    console.error("Failed to load WhatsApp config:", err);
  }
}

async function loadAiProviderConfig() {
  try {
    const config = await adminApi("/admin/config/ai-providers");
    document.getElementById("aiActiveProvider").value = config.active_provider || "gemini";
    document.getElementById("aiGeminiKey").value = config.gemini_api_key || "";
    document.getElementById("aiGeminiModel").value = config.gemini_model || "";
    document.getElementById("aiClaudeKey").value = config.claude_api_key || "";
    document.getElementById("aiClaudeModel").value = config.claude_model || "";
    document.getElementById("aiOpenaiKey").value = config.openai_api_key || "";
    document.getElementById("aiOpenaiModel").value = config.openai_model || "";
  } catch (err) {
    console.error("Failed to load AI provider config:", err);
  }
}

// Event listeners for complete appointment and prescription/report forms
if (document.getElementById("completeForm")) {
  document.getElementById("completeForm").addEventListener("submit", submitCompleteAppointment);
}
if (document.getElementById("prescriptionForm")) {
  document.getElementById("prescriptionForm").addEventListener("submit", submitPrescription);
}
if (document.getElementById("medicalReportForm")) {
  document.getElementById("medicalReportForm").addEventListener("submit", submitMedicalReport);
}

const notificationConfigForm = document.getElementById("notificationConfigForm");
if (notificationConfigForm) {
  notificationConfigForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("saveNotificationConfigButton");
  const originalText = btn.textContent;
  btn.textContent = "Saving...";
  btn.disabled = true;

  const data = {
    twilio_account_sid: document.getElementById("configTwilioSid").value.trim(),
    twilio_auth_token: document.getElementById("configTwilioAuth").value.trim(),
    twilio_from_number: document.getElementById("configTwilioFrom").value.trim(),
    smtp_host: document.getElementById("configSmtpHost").value.trim(),
    smtp_port: document.getElementById("configSmtpPort").value.trim(),
    smtp_username: document.getElementById("configSmtpUser").value.trim(),
    smtp_password: document.getElementById("configSmtpPass").value.trim(),
    smtp_from: document.getElementById("configSmtpFrom").value.trim(),
  };

    try {
      await adminApi("/admin/config/notifications", {
        method: "POST",
        body: JSON.stringify(data)
      });
      alert("Configuration saved successfully.");
    } catch (err) {
      if (err.message !== "Unauthorized") {
        alert(`Couldn't save config: ${err.message}`);
      }
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  });
}

const whatsappConfigForm = document.getElementById("whatsappConfigForm");
if (whatsappConfigForm) {
  whatsappConfigForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("saveWhatsappConfigButton");
    const originalText = btn.textContent;
    btn.textContent = "Saving...";
    btn.disabled = true;

    const data = {
      access_token: document.getElementById("configWhatsappToken").value.trim(),
      phone_number_id: document.getElementById("configWhatsappPhoneId").value.trim(),
      business_account_id: document.getElementById("configWhatsappBizId").value.trim(),
      verify_token: document.getElementById("configWhatsappVerifyToken").value.trim(),
      api_version: document.getElementById("configWhatsappApiVersion").value.trim(),
    };

    try {
      await adminApi("/admin/config/whatsapp", {
        method: "POST",
        body: JSON.stringify(data),
      });
      alert("WhatsApp configuration saved successfully.");
    } catch (err) {
      if (err.message !== "Unauthorized") {
        alert(`Couldn't save WhatsApp config: ${err.message}`);
      }
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  });
}

const aiProviderConfigForm = document.getElementById("aiProviderConfigForm");
if (aiProviderConfigForm) {
  aiProviderConfigForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("saveAiProviderConfigButton");
    const originalText = btn.textContent;
    btn.textContent = "Saving...";
    btn.disabled = true;

    const data = {
      active_provider: document.getElementById("aiActiveProvider").value,
      gemini_api_key: document.getElementById("aiGeminiKey").value.trim(),
      gemini_model: document.getElementById("aiGeminiModel").value.trim(),
      claude_api_key: document.getElementById("aiClaudeKey").value.trim(),
      claude_model: document.getElementById("aiClaudeModel").value.trim(),
      openai_api_key: document.getElementById("aiOpenaiKey").value.trim(),
      openai_model: document.getElementById("aiOpenaiModel").value.trim(),
    };

    try {
      await adminApi("/admin/config/ai-providers", {
        method: "POST",
        body: JSON.stringify(data),
      });
      alert("AI provider configuration saved successfully.");
    } catch (err) {
      if (err.message !== "Unauthorized") {
        alert(`Couldn't save AI provider config: ${err.message}`);
      }
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  });
}

function initAdminForms() {
  document.getElementById("doctorForm").addEventListener("submit", submitDoctorForm);
  document.getElementById("cancelDoctorEdit").addEventListener("click", () => {
    resetDoctorForm();
    showDoctorForm(false);
  });
  document.getElementById("closeDoctorModal").addEventListener("click", () => {
    resetDoctorForm();
    showDoctorForm(false);
  });

  document.getElementById("branchForm").addEventListener("submit", submitBranchForm);
  document.getElementById("cancelBranchEdit").addEventListener("click", () => {
    resetBranchForm();
    showBranchForm(false);
  });
  document.getElementById("closeBranchModal").addEventListener("click", () => {
    resetBranchForm();
    showBranchForm(false);
  });

  document.getElementById("refreshDoctors").addEventListener("click", loadDoctorManagement);
  document.getElementById("refreshBranches").addEventListener("click", loadBranches);
  document.getElementById("refreshPatients")?.addEventListener("click", loadPatients);
  document.getElementById("exportPatientsCsv")?.addEventListener("click", () => downloadPatientExport("csv"));
  document.getElementById("exportPatientsXlsx")?.addEventListener("click", () => downloadPatientExport("xlsx"));
  document.getElementById("patientImportFile")?.addEventListener("change", importPatientsPreview);
  document.getElementById("closePatientDetailsModal")?.addEventListener("click", () => {
    document.getElementById("patientDetailsModal").hidden = true;
  });
  document.getElementById("addDoctorBtn").addEventListener("click", openAddDoctorForm);
  document.getElementById("addBranchBtn").addEventListener("click", openAddBranchForm);
  document.getElementById("patientFormModal")?.addEventListener("submit", submitPatientForm);
  document.getElementById("closePatientModal")?.addEventListener("click", () => {
    document.getElementById("patientModal").hidden = true;
    resetPatientForm();
  });
  document.getElementById("cancelPatientEdit")?.addEventListener("click", () => {
    document.getElementById("patientModal").hidden = true;
    resetPatientForm();
  });

  document.getElementById("refreshConversations")?.addEventListener("click", loadConversations);
  ["fConvSearch", "fConvSource"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener(el.type === "text" ? "input" : "change", () => {
        convState.search = document.getElementById("fConvSearch").value.trim();
        convState.source = document.getElementById("fConvSource").value;
        loadConversations();
      });
    }
  });
  document.getElementById("fConvSource")?.addEventListener("change", () => {
    convState.source = document.getElementById("fConvSource").value;
    loadConversations();
  });
  document.getElementById("inboxBackBtn")?.addEventListener("click", () => {
    document.getElementById("inboxWrap")?.classList.remove("chat-open");
  });
}

// ---------------------------------------------------------------------------
// Conversations tab
// ---------------------------------------------------------------------------

/**
 * WhatsApp-style relative day label. Recomputed against `new Date()` every
 * call, so it is never stale/hardcoded — a message shown as "Monday" today
 * will correctly become "Mon, 8 Sep" (or similar) once 7+ days have passed,
 * with no stored label or batch job needed.
 *
 *   0 days ago   -> "Today" (or a time, e.g. "10:42 AM", if requested)
 *   1 day ago    -> "Yesterday"
 *   2-6 days ago -> weekday name, e.g. "Monday"
 *   7+ days ago  -> short absolute date, e.g. "3 Sep 2026"
 */
function formatRelativeDayLabel(date, { timeForToday = false } = {}) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86400000);

  if (diffDays === 0) {
    return timeForToday
      ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : "Today";
  }
  if (diffDays === 1) return "Yesterday";
  if (diffDays > 1 && diffDays < 7) return date.toLocaleDateString([], { weekday: "long" });
  return date.toLocaleDateString([], { day: "numeric", month: "short", year: diffDays > 330 ? "numeric" : undefined });
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

// Currently open conversation, so a re-render (e.g. after search) can
// keep the reader panel's selection highlighted and intact.
let activeConversationId = null;

async function loadConversations() {
  const list = document.getElementById("inboxList");
  list.innerHTML = `<div class="loading">Loading conversations...</div>`;
  try {
    const params = new URLSearchParams();
    if (convState.search) params.set("search", convState.search);
    if (convState.source) params.set("source", convState.source);
    const qs = params.toString();
    const conversations = await adminApi(`/admin/conversations${qs ? `?${qs}` : ""}`);
    convState.conversations = conversations;
    renderConversationList(conversations);
  } catch (err) {
    if (err.message !== "Unauthorized") {
      list.innerHTML = `<div class="empty-note">Couldn't load conversations: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderConversationList(conversations) {
  const list = document.getElementById("inboxList");
  const count = document.getElementById("inboxListCount");
  count.textContent = `${conversations.length} conversation${conversations.length === 1 ? "" : "s"}`;

  if (!conversations.length) {
    list.innerHTML = `<div class="empty-note">No conversations found.</div>`;
    // Nothing to show on the right either.
    activeConversationId = null;
    resetInboxChatPanel();
    return;
  }

  list.innerHTML = conversations.map((c) => `
    <button type="button" class="inbox-card ${c.id === activeConversationId ? "active" : ""}" data-id="${c.id}">
      <span class="conv-avatar">${escapeHtml(initials(c.user_name))}</span>
      <span class="inbox-card-body">
        <span class="inbox-card-top">
          <span class="inbox-card-name">${escapeHtml(c.user_name || "Unknown")}</span>
          <span class="inbox-card-time">${c.last_message_at ? escapeHtml(formatRelativeDayLabel(new Date(c.last_message_at), { timeForToday: true })) : ""}</span>
        </span>
        <span class="inbox-card-preview">${escapeHtml(c.last_message || "No messages yet")}</span>
        <span class="inbox-card-meta">
          ${(c.sources || []).map((s) => `<span class="source-pill ${escapeHtml(s)}">${escapeHtml(SOURCE_LABEL[s] || s)}</span>`).join("")}
          <span class="inbox-card-count">${escapeHtml(String(c.message_count ?? 0))}</span>
        </span>
      </span>
    </button>
  `).join("");

  list.querySelectorAll(".inbox-card").forEach((card) => {
    card.addEventListener("click", () => openConversation(Number(card.dataset.id)));
  });

  // If the conversation open in the reader panel is still in this list
  // (e.g. after a search/filter change), leave it open as-is.
  if (activeConversationId && !conversations.some((c) => c.id === activeConversationId)) {
    activeConversationId = null;
    resetInboxChatPanel();
  }
}

function resetInboxChatPanel() {
  document.getElementById("inboxWrap")?.classList.remove("chat-open");
  document.getElementById("inboxChatHead").hidden = true;
  document.getElementById("inboxChatEmpty").hidden = false;
  document.getElementById("chatThread").innerHTML = "";
}

async function openConversation(id) {
  const convo = convState.conversations.find((c) => c.id === id);
  const thread = document.getElementById("chatThread");
  const title = document.getElementById("conversationModalTitle");
  const sub = document.getElementById("conversationModalSub");
  const avatar = document.getElementById("conversationModalAvatar");

  activeConversationId = id;
  document.querySelectorAll(".inbox-card").forEach((card) => {
    card.classList.toggle("active", Number(card.dataset.id) === id);
  });

  document.getElementById("inboxWrap")?.classList.add("chat-open");
  document.getElementById("inboxChatEmpty").hidden = true;
  document.getElementById("inboxChatHead").hidden = false;

  title.textContent = convo ? (convo.user_name || "Unknown user") : "Conversation";
  avatar.textContent = initials(convo ? convo.user_name : "");
  sub.textContent = convo
    ? `${(convo.sources || []).map((s) => SOURCE_LABEL[s] || s).join(" + ")}${convo.mobile ? " · " + convo.mobile : ""}`
    : "";
  thread.innerHTML = `<div class="loading">Loading conversation...</div>`;

  try {
    const messages = await adminApi(`/admin/conversations/${id}/messages`);
    // Guard against a slower request landing after the user has already
    // clicked a different conversation in the meantime.
    if (activeConversationId === id) renderChatThread(messages);
  } catch (err) {
    if (err.message !== "Unauthorized" && activeConversationId === id) {
      thread.innerHTML = `<div class="empty-note">Couldn't load conversation: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderMarkdown(text) {
  if (!text) return "";
  const raw = String(text);
  // The bot's own reply text uses WhatsApp-style single markers
  // (*bold*, _italic_, ~strike~) rather than standard Markdown
  // (**bold**, *italic*, ~~strike~~) — convert before parsing so it
  // renders as actually bold/italic instead of the wrong style.
  const mdSource = raw
    .replace(/(?<!\*)\*(?!\*)(\S(?:[^*\n]*\S)?)\*(?!\*)/g, "**$1**")
    .replace(/(^|[^\w])_(\S(?:[^_\n]*\S)?)_(?!\w)/g, "$1*$2*")
    .replace(/(?<!~)~(?!~)(\S(?:[^~\n]*\S)?)~(?!~)/g, "~~$1~~");

  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    // Markdown libraries didn't load (e.g. offline) — fall back to plain
    // escaped text rather than showing nothing.
    return escapeHtml(raw);
  }
  const html = marked.parse(mdSource, { breaks: true });
  return DOMPurify.sanitize(html);
}

function renderChatThread(messages) {
  const thread = document.getElementById("chatThread");
  if (!messages.length) {
    thread.innerHTML = `<div class="empty-note">No messages in this conversation.</div>`;
    return;
  }

  // Group consecutive messages under a WhatsApp-style day divider.
  // The divider is the ONLY place a date appears — bubbles themselves
  // only ever show a time.
  let html = "";
  let lastDayKey = null;

  messages.forEach((m) => {
    const ts = m.timestamp ? new Date(m.timestamp) : null;
    if (ts) {
      const dayKey = ts.toDateString();
      if (dayKey !== lastDayKey) {
        lastDayKey = dayKey;
        html += `<div class="chat-day-divider"><span>${escapeHtml(formatRelativeDayLabel(ts))}</span></div>`;
      }
    }

    const isUser = (m.sender || "").toUpperCase() === "USER";
    const time = ts ? ts.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    const sourceLabel = SOURCE_LABEL[m.source] || m.source;
    html += `
      <div class="chat-row ${isUser ? "user" : "bot"}">
        <div class="chat-bubble">
          ${m.source ? `<span class="chat-source-tag">${escapeHtml(sourceLabel)}</span>` : ""}
          <div class="chat-bubble-markdown">${renderMarkdown(m.text)}</div>
          ${time ? `<span class="chat-time">${escapeHtml(time)}</span>` : ""}
        </div>
      </div>
    `;
  });

  thread.innerHTML = html;
  thread.scrollTop = thread.scrollHeight;
}

// ---------------------------------------------------------------------------
// Roles & Permissions
// ---------------------------------------------------------------------------

let rolesData = [];
let permissionsData = [];
let currentRolePermissions = [];
let initialRolesLoad = true;

async function loadRolesAndPermissions() {
  try {
    const [roles, perms] = await Promise.all([
      adminApi("/admin/roles"),
      adminApi("/admin/permissions")
    ]);
    rolesData = roles;
    permissionsData = perms;

    // Populate role dropdown
    const select = document.getElementById("roleSelect");
    const prevSelectedId = select.value;

    select.innerHTML = '<option value="">-- Select a Role --</option>' +
      roles.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('');

    // Populate permissions creation container (for new roles)
    const newRoleContainer = document.getElementById("newRolePermissionsContainer");
    newRoleContainer.innerHTML = renderPermissionsGrouped(perms, "newRole");

    if (prevSelectedId && Array.from(select.options).some(o => o.value === prevSelectedId)) {
        select.value = prevSelectedId;
    } else if (initialRolesLoad) {
        initialRolesLoad = false;
        const adminRole = roles.find(r => r.name === "ADMIN");
        if (adminRole) {
            select.value = adminRole.id;
            select.dispatchEvent(new Event("change"));
        }
    }

  } catch (err) {
    if (err.message !== "Unauthorized") {
      alert("Failed to load roles: " + err.message);
    }
  }
}

function renderPermissionsGrouped(perms, prefix = "perm") {
  const byModule = {};
  perms.forEach(p => {
    const mod = p.module || 'General';
    if (!byModule[mod]) byModule[mod] = [];
    byModule[mod].push(p);
  });

  let html = '';
  for (const mod in byModule) {
    html += `<div style="margin-bottom: 12px;">
      <div style="font-weight: 600; font-size: 0.9em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid var(--border);">${escapeHtml(mod)}</div>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px;">`;

    byModule[mod].forEach(p => {
      html += `
        <label style="display: flex; align-items: center; gap: 8px; font-size: 0.95em; cursor: pointer;">
          <span class="toggle-switch">
            <input type="checkbox" name="permissions" class="${prefix}-checkbox" value="${escapeHtml(p.code)}">
            <span class="toggle-slider"></span>
          </span>
          <span title="${escapeHtml(p.description)}">${escapeHtml(p.name)}</span>
        </label>
      `;
    });

    html += `</div></div>`;
  }
  return html;
}

document.getElementById("roleSelect")?.addEventListener("change", async (e) => {
  const roleId = e.target.value;
  const form = document.getElementById("rolePermissionsForm");
  const container = document.getElementById("permissionsContainer");
  const infoDisplay = document.getElementById("roleInfoDisplay");

  if (!roleId) {
    form.hidden = true;
    infoDisplay.innerHTML = "";
    return;
  }

  try {
    const roleDetails = await adminApi(`/admin/roles/${roleId}`);
    currentRolePermissions = roleDetails.permissions.map(p => p.code);

    infoDisplay.innerHTML = roleDetails.is_system_role
      ? `<span style="display: inline-flex; align-items: center; gap: 4px; color: #b18c00; background: #fff5cc; padding: 3px 8px; border-radius: 4px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> System Role</span>`
      : `<span style="display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); padding: 3px 8px; border-radius: 4px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> Custom Role</span>`;

    // Render checkboxes
    container.innerHTML = renderPermissionsGrouped(permissionsData, "editRole");

    // Check the ones they have
    const isSuperAdmin = roleDetails.name === "SUPER_ADMIN";

    container.querySelectorAll(".editRole-checkbox").forEach(cb => {
      cb.checked = isSuperAdmin || currentRolePermissions.includes(cb.value);
      cb.disabled = isSuperAdmin; // cannot edit SUPER_ADMIN permissions via UI directly like this
    });

    document.getElementById("saveRoleChangesBtn").disabled = isSuperAdmin;
    document.getElementById("selectAllPermsBtn").disabled = isSuperAdmin;
    document.getElementById("clearAllPermsBtn").disabled = isSuperAdmin;
    document.getElementById("resetRoleChangesBtn").disabled = isSuperAdmin;

    if (isSuperAdmin) {
        infoDisplay.innerHTML += `<div style="margin-top: 6px;">Super Admin has implied access to all permissions.</div>`;
    }

    form.hidden = false;
  } catch (err) {
    alert("Failed to load role details: " + err.message);
  }
});

document.getElementById("selectAllPermsBtn")?.addEventListener("click", () => {
  document.querySelectorAll(".editRole-checkbox:not(:disabled)").forEach(cb => cb.checked = true);
});

document.getElementById("clearAllPermsBtn")?.addEventListener("click", () => {
  document.querySelectorAll(".editRole-checkbox:not(:disabled)").forEach(cb => cb.checked = false);
});

document.getElementById("resetRoleChangesBtn")?.addEventListener("click", () => {
  document.querySelectorAll(".editRole-checkbox:not(:disabled)").forEach(cb => {
    cb.checked = currentRolePermissions.includes(cb.value);
  });
});

document.getElementById("rolePermissionsForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const roleId = document.getElementById("roleSelect").value;
  if (!roleId) return;

  const selected = Array.from(document.querySelectorAll(".editRole-checkbox:checked"))
    .map(cb => cb.value);

  const btn = document.getElementById("saveRoleChangesBtn");
  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    await adminApi(`/admin/roles/${roleId}/permissions`, {
      method: "PUT",
      body: JSON.stringify({ permissions: selected })
    });
    showStatusModal("Success", "Role permissions updated successfully.");
    currentRolePermissions = selected;
  } catch (err) {
    showStatusModal("Error", "Failed to update permissions: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
});

document.getElementById("refreshRolesBtn")?.addEventListener("click", loadRolesAndPermissions);

document.getElementById("createRoleBtn")?.addEventListener("click", () => {
  document.getElementById("createRoleForm").reset();
  document.getElementById("createRoleModal").hidden = false;
});

document.getElementById("closeCreateRoleModal")?.addEventListener("click", () => {
  document.getElementById("createRoleModal").hidden = true;
});
document.getElementById("cancelCreateRoleBtn")?.addEventListener("click", () => {
  document.getElementById("createRoleModal").hidden = true;
});

document.getElementById("createRoleForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("newRoleName").value.trim().toUpperCase().replace(/\s+/g, '_');
  const description = document.getElementById("newRoleDesc").value.trim();

  const selected = Array.from(document.querySelectorAll(".newRole-checkbox:checked"))
    .map(cb => cb.value);

  if (!name) return;

  const btn = e.target.querySelector("button[type='submit']");
  btn.disabled = true;
  btn.textContent = "Creating...";

  try {
    await adminApi("/admin/roles", {
      method: "POST",
      body: JSON.stringify({ name, description, permissions: selected })
    });
    document.getElementById("createRoleModal").hidden = true;
    showStatusModal("Success", `Role ${name} created successfully.`);
    await loadRolesAndPermissions();

    // Auto-select the new role
    const select = document.getElementById("roleSelect");
    for (let i = 0; i < select.options.length; i++) {
      if (select.options[i].text === name) {
        select.selectedIndex = i;
        select.dispatchEvent(new Event("change"));
        break;
      }
    }
  } catch (err) {
    showStatusModal("Error", "Failed to create role: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Create Role";
  }
});

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function formatTime(t) {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Init — try stored credentials first so a page refresh doesn't force re-login
// ---------------------------------------------------------------------------


wireSidebarTabs();
initSidebarChrome();
initAdminForms();


(async function init() {
  if (getAuthHeader()) {
    try {
      const me = await adminApi("/auth/me");
      sessionStorage.setItem('ROLES', JSON.stringify([me.role]));
      sessionStorage.setItem('PERMISSIONS', JSON.stringify(me.permissions || []));
      await showDashboard();

      // Auto-fetch active tab data every 30 seconds
      setInterval(() => {
        if (!document.getElementById("adminShell").hidden) {
          const activeBtn = document.querySelector(".sidebar-nav .nav-item.active");
          if (activeBtn) {
            const activeTab = activeBtn.dataset.tab;
            if (activeTab === "booking") {
                loadBookings();
                loadStats();
            } else if (activeTab === "doctors") {
                loadDoctorManagement();
            } else if (activeTab === "patients") {
                loadPatients();
            } else if (activeTab === "branches") {
                loadBranches();
            } else if (activeTab === "departments") {
                loadAdminDepartments();
            } else if (activeTab === "roles") {
                loadRolesAndPermissions();
            } else if (activeTab === "notifications") {
                loadNotificationConfig();
            }
          }
        }
      }, 30000);

      return;
    } catch (_) {
      // fall through to login screen (already shown by the 401 handler)
    }
  }
  showLogin();
})();

// ==========================================
// ROLE USERS
// ==========================================

let currentUsersData = [];

async function loadRoleUsers() {
    try {
        currentUsersData = await adminApi("/admin/users");
        if (!Array.isArray(currentUsersData)) {
            console.warn("Expected array of users, got:", currentUsersData);
            currentUsersData = currentUsersData.users || [];
        }
        renderRoleUsers(currentUsersData);
    } catch (e) {
        console.error("Failed to load users", e);
        alert("Failed to load users from database: " + e.message);
    }

    // Always try to load dropdowns even if users fail
    try {
        await populateRoleUserDropdowns();
    } catch (e) {
        console.error("Failed to load dropdowns", e);
    }
}

function renderRoleUsers(users) {
    const tbody = document.getElementById("roleUsersTableBody");
    if (!tbody) return;

    // Check if filtering is applied
    const search = document.getElementById("fUserSearch").value.toLowerCase();
    const role = document.getElementById("fUserRole").value;
    const branch = document.getElementById("fUserBranch").value;
    const department = document.getElementById("fUserDepartment").value;
    const status = document.getElementById("fUserStatus").value;

    const filtered = users.filter(u => {
        if (search) {
            const nameMatch = (u.name || "").toLowerCase().includes(search);
            const emailMatch = (u.email || "").toLowerCase().includes(search);
            if (!nameMatch && !emailMatch) return false;
        }
        if (role && u.role_id != role) return false;
        if (branch && u.branch_id != branch) return false;
        if (department && u.department_id != department) return false;
        if (status !== "" && u.is_active != status) return false;
        return true;
    });

    tbody.innerHTML = filtered.map(u => `
        <tr>
            <td>${u.id}</td>
            <td>${u.name}</td>
            <td>${u.email}</td>
            <td>${u.role_name}</td>
            <td>${u.branch_name || 'N/A'}</td>
            <td>${u.department_name || 'N/A'}</td>
            <td><span class="status-badge ${u.is_active ? 'success' : 'danger'}">${u.is_active ? 'Active' : 'Inactive'}</span></td>
            <td>
                <button class="btn btn-ghost btn-small" onclick="openEditUserModal(${u.id})">Edit</button>
                <button class="btn btn-ghost btn-small" onclick="openChangePasswordModal(${u.id})">Password</button>
            </td>
        </tr>
    `).join("");
}

async function populateRoleUserDropdowns() {
    try {
        const [rolesRes, branchesRes, deptsRes] = await Promise.all([
            adminApi("/admin/roles").catch(() => []),
            adminApi("/admin/branches").catch(() => []),
            adminApi("/departments/all").catch(() => [])
        ]);

        const roles = Array.isArray(rolesRes) ? rolesRes : (rolesRes.roles || []);
        const branches = Array.isArray(branchesRes) ? branchesRes : [];
        const depts = Array.isArray(deptsRes) ? deptsRes : (deptsRes.departments || []);

        const roleOpts = `<option value="">Select Role</option>` + roles.map(r => `<option value="${r.id}">${r.name}</option>`).join("");
        const branchOpts = `<option value="">Select Branch</option>` + branches.map(b => `<option value="${b.id}">${b.name}</option>`).join("");
        const deptOpts = `<option value="">Select Department</option>` + depts.map(d => `<option value="${d.id}">${d.name}</option>`).join("");

        document.getElementById("fUserRole").innerHTML = `<option value="">All Roles</option>` + roleOpts.replace('<option value="">Select Role</option>', '');
        document.getElementById("fUserBranch").innerHTML = `<option value="">All Branches</option>` + branchOpts.replace('<option value="">Select Branch</option>', '');
        document.getElementById("fUserDepartment").innerHTML = `<option value="">All Departments</option>` + deptOpts.replace('<option value="">Select Department</option>', '');

        document.getElementById("userRoleField").innerHTML = roleOpts;
        document.getElementById("userBranchField").innerHTML = branchOpts;
        document.getElementById("userDepartmentField").innerHTML = deptOpts;
    } catch (e) {}
}

["fUserSearch", "fUserRole", "fUserBranch", "fUserDepartment", "fUserStatus"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener(el.type === "text" ? "input" : "change", () => {
            renderRoleUsers(currentUsersData);
        });
    }
});

function openCreateUserModal() {
    document.getElementById("userForm").reset();
    document.getElementById("userIdField").value = "";
    document.getElementById("userFormModalTitle").innerText = "Create New User";
    document.getElementById("userPasswordFieldContainer").hidden = false;
    document.getElementById("userConfirmPasswordFieldContainer").hidden = false;
    document.getElementById("userPasswordField").required = true;
    document.getElementById("userConfirmPasswordField").required = true;
    document.getElementById("userStatusContainer").hidden = true;
    document.getElementById("userFormModal").hidden = false;
}

function openEditUserModal(id) {
    const user = currentUsersData.find(u => u.id === id);
    if(!user) return;

    document.getElementById("userForm").reset();
    document.getElementById("userIdField").value = user.id;
    document.getElementById("userNameField").value = user.name;
    document.getElementById("userEmailField").value = user.email;
    document.getElementById("userRoleField").value = user.role_id;

    document.getElementById("userBranchField").value = user.branch_id || "";
    document.getElementById("userDepartmentField").value = user.department_id || "";

    document.getElementById("userStatusField").value = user.is_active;

    document.getElementById("userFormModalTitle").innerText = "Edit User";
    document.getElementById("userPasswordFieldContainer").hidden = true;
    document.getElementById("userConfirmPasswordFieldContainer").hidden = true;
    document.getElementById("userPasswordField").required = false;
    document.getElementById("userConfirmPasswordField").required = false;
    document.getElementById("userStatusContainer").hidden = false;
    document.getElementById("userFormModal").hidden = false;
}

function closeUserFormModal() {
    document.getElementById("userFormModal").hidden = true;
}

function handleUserRoleChange() {
    // Dynamic logic if needed based on role selected
}

function handleUserBranchChange() {
    // Dynamic logic to filter departments if needed
}

async function submitUserForm(e) {
    e.preventDefault();
    const id = document.getElementById("userIdField").value;
    const isEdit = !!id;

    const payload = {
        name: document.getElementById("userNameField").value,
        email: document.getElementById("userEmailField").value,
        role_id: parseInt(document.getElementById("userRoleField").value),
        branch_id: document.getElementById("userBranchField").value ? parseInt(document.getElementById("userBranchField").value) : null,
        department_id: document.getElementById("userDepartmentField").value ? parseInt(document.getElementById("userDepartmentField").value) : null
    };

    if (isEdit) {
        payload.is_active = parseInt(document.getElementById("userStatusField").value);
    } else {
        const p1 = document.getElementById("userPasswordField").value;
        const p2 = document.getElementById("userConfirmPasswordField").value;
        if(p1 !== p2) {
            alert("Passwords do not match!");
            return;
        }
        payload.password = p1;
    }

    try {
        const method = isEdit ? "PUT" : "POST";
        const endpoint = isEdit ? `/admin/users/${id}` : "/admin/users";
        await adminApi(endpoint, { method, body: JSON.stringify(payload) });
        closeUserFormModal();
        loadRoleUsers();
    } catch(err) {
        alert("Error saving user: " + err.message);
    }
}

function openChangePasswordModal(id) {
    document.getElementById("changePasswordForm").reset();
    document.getElementById("cpUserIdField").value = id;
    document.getElementById("changePasswordModal").hidden = false;
}

async function submitChangePassword(e) {
    e.preventDefault();
    const id = document.getElementById("cpUserIdField").value;
    const p1 = document.getElementById("cpNewPasswordField").value;
    const p2 = document.getElementById("cpConfirmPasswordField").value;

    if(p1 !== p2) {
        alert("Passwords do not match!");
        return;
    }

    try {
        await adminApi(`/admin/users/${id}/password`, {
            method: "PUT",
            body: JSON.stringify({ new_password: p1, confirm_password: p2 })
        });
        document.getElementById("changePasswordModal").hidden = true;
        alert("Password updated successfully");
    } catch(err) {
        alert("Error changing password: " + err.message);
    }
}

// Expose modal and form handlers to window for HTML onclick attributes
window.openCreateUserModal = openCreateUserModal;
window.openEditUserModal = openEditUserModal;
window.closeUserFormModal = closeUserFormModal;
window.submitUserForm = submitUserForm;
window.openChangePasswordModal = openChangePasswordModal;
window.submitChangePassword = submitChangePassword;
window.handleUserRoleChange = handleUserRoleChange;
window.handleUserBranchChange = handleUserBranchChange;

// ---------------------------------------------------------------------------
// Department Management
// ---------------------------------------------------------------------------

function showDepartmentForm(show) {
  document.getElementById("departmentModal").hidden = !show;
}

document.getElementById("addDepartmentBtn")?.addEventListener("click", () => {
  adminState.departmentEditId = null;
  document.getElementById("departmentFormTitle").textContent = "Add new department";
  document.getElementById("departmentForm").reset();
  document.getElementById("departmentStatus").value = "ACTIVE";
  document.getElementById("saveDepartmentButton").textContent = "Save department";
  document.getElementById("cancelDepartmentEdit").hidden = true;
  showDepartmentForm(true);
});

document.getElementById("closeDepartmentModal")?.addEventListener("click", () => showDepartmentForm(false));
document.getElementById("cancelDepartmentEdit")?.addEventListener("click", () => showDepartmentForm(false));

document.getElementById("departmentForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const payload = {
    name: form.name.value.trim(),
    description: form.description.value.trim() || null,
    department_status: form.department_status.value
  };

  try {
    if (adminState.departmentEditId) {
      await adminApi(`/admin/departments/${adminState.departmentEditId}`, { method: "PUT", body: JSON.stringify(payload) });
      alert("Department updated");
    } else {
      await adminApi("/admin/departments", { method: "POST", body: JSON.stringify(payload) });
      alert("Department created");
    }
    showDepartmentForm(false);
    await loadAdminDepartments();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

async function loadAdminDepartments() {
  const tbody = document.getElementById("departmentTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="empty-note">Loading departments&hellip;</td></tr>`;
  try {
    const departments = await adminApi("/admin/departments");
    adminState.departments = departments;
    
    if (!departments.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-note">No departments found</td></tr>`;
      return;
    }
    renderDepartmentList(departments);
  } catch (err) {
    if (err.message !== "Unauthorized") {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-note">Couldn't load departments: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

function renderDepartmentList(departments) {
  const tbody = document.getElementById("departmentTableBody");
  if (!tbody) return;
  tbody.innerHTML = departments
    .map((d) => `
      <tr>
        <td>${d.id}</td>
        <td>${escapeHtml(d.name)}</td>
        <td>${escapeHtml(d.description || "-")}</td>
        <td><span class="status-pill ${d.department_status}">${d.department_status}</span></td>
        <td>
          <button class="btn btn-ghost btn-small edit-department" data-id="${d.id}">Edit</button>
          <button class="btn btn-ghost btn-small delete-department" data-id="${d.id}">Delete</button>
        </td>
      </tr>
    `)
    .join("");

  tbody.querySelectorAll(".edit-department").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dept = adminState.departments.find((d) => String(d.id) === String(btn.dataset.id));
      if (!dept) { alert("Department not found."); return; }
      adminState.departmentEditId = dept.id;
      document.getElementById("departmentFormTitle").textContent = "Edit department";
      document.getElementById("departmentName").value = dept.name;
      document.getElementById("departmentDescription").value = dept.description || "";
      document.getElementById("departmentStatus").value = dept.department_status;
      document.getElementById("saveDepartmentButton").textContent = "Update department";
      document.getElementById("cancelDepartmentEdit").hidden = false;
      showDepartmentForm(true);
    });
  });

  tbody.querySelectorAll(".delete-department").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this department? It cannot be deleted if assigned to doctors.")) return;
      try {
        await adminApi(`/admin/departments/${btn.dataset.id}`, { method: "DELETE" });
        await loadAdminDepartments();
      } catch (err) {
        alert(`Couldn't delete department: ${err.message}`);
      }
    });
  });
}

document.getElementById("departmentSearch")?.addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  const filtered = adminState.departments.filter(d => 
    d.name.toLowerCase().includes(q) || (d.description && d.description.toLowerCase().includes(q))
  );
  if (!filtered.length) {
      document.getElementById("departmentTableBody").innerHTML = `<tr><td colspan="5" class="empty-note">No matching departments</td></tr>`;
  } else {
      renderDepartmentList(filtered);
  }
});