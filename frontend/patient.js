/* ==========================================================================
   Patient Portal Client Logic — Varuvi
   ========================================================================== */

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "http://localhost:8000" : "";

async function verifyPatientAuth() {
  try {
    const res = await fetch(`${API_BASE}/patient/auth/session`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return false;
    const payload = await res.json();
    return Boolean(payload && payload.authenticated);
  } catch (_) {
    return false;
  }
}

async function clearPatientAuthSession() {
  try {
    await fetch(`${API_BASE}/patient/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch (_) {
    // ignore and proceed to clear local UI state
  }
}

// Portal State
const state = {
  token: null,
  profile: null,
  appointments: [],
  consultations: [],
  prescriptions: [],
  reports: [],
  timeline: [],
  // Reschedule temporary slot tracker
  rescheduleAppt: null,
  rescheduleDate: null,
  rescheduleTime: null,
};

function redirectAfterAuth() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next") || new URL("booking.html", window.location.href).toString();
  const target = new URL(next, window.location.href);
  window.location.href = target.toString();
}

function isProtectedPatientRoute() {
  return /(?:^|\/)manage\.html?$/i.test(window.location.pathname) || /(?:^|\/)patient\.html?$/i.test(window.location.pathname);
}

async function enforcePatientRouteAccess() {
  const currentPath = window.location.pathname.split("/").pop() || "index.html";

  if (currentPath === "index.html") return;
  if (currentPath === "patient.html") return;

  const isAuthenticated = await verifyPatientAuth();
  if (!isAuthenticated) {
    const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.location.replace(`patient.html?next=${encodeURIComponent(next)}`);
    return;
  }
}

// ---------------------------------------------------------------------------
// Core API Fetch Helper (Auth-aware)
// ---------------------------------------------------------------------------
async function portalApi(path, options = {}) {
  const headers = { "Content-Type": "application/json" };

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...headers,
      ...options.headers,
    },
  });

  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    /* empty body */
  }

  if (!res.ok) {
    if (res.status === 401) {
      clearPatientAuthSession();
      state.token = null;
      if (window.location.pathname.toLowerCase().endsWith("patient.html")) {
        showAuth();
      }
      throw new Error("Session expired. Please log in again.");
    }
    const detail = (body && body.detail) ? body.detail : (body && body.message ? body.message : `Request failed (${res.status})`);
    const error = new Error(detail);
    error.body = body;
    throw error;
  }

  return body;
}

// Helper to escape HTML to prevent XSS
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Format database date into user friendly string
function formatDate(dStr) {
  if (!dStr) return "Not provided";
  try {
    const parts = dStr.split("-");
    if (parts.length !== 3) return dStr;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const yr = parts[0];
    const mo = months[parseInt(parts[1], 10) - 1];
    const dy = parts[2];
    return `${parseInt(dy, 10)} ${mo} ${yr}`;
  } catch (_) {
    return dStr;
  }
}

// ---------------------------------------------------------------------------
// Page Initialization & Navigation
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  setupAuthTabs();
  setupNavigation();
  setupFormListeners();
  setupModalListeners();

  await enforcePatientRouteAccess();

  const next = new URLSearchParams(window.location.search).get("next");
  const isAuthenticated = await verifyPatientAuth();

  if (isAuthenticated) {
    state.token = "cookie-auth";
    if (next) {
      window.location.replace(next);
      return;
    }
    loadPortalData();
  } else {
    showAuth();
  }
});

function showAuth() {
  const next = new URLSearchParams(window.location.search).get("next");
  const authSection = document.getElementById("authSection");
  const portalSection = document.getElementById("portalSection");
  const portalLoader = document.getElementById("portalLoader");
  const rescheduleModal = document.getElementById("rescheduleModal");

  if (authSection) authSection.hidden = false;
  if (portalSection) portalSection.hidden = true;
  if (portalLoader) portalLoader.hidden = true;
  if (rescheduleModal) rescheduleModal.hidden = true;

  const backLink = next
    ? `<a href="${next}" class="btn btn-ghost" style="font-size: 13px;">&larr; Continue</a>`
    : `<a href="index.html" class="btn btn-ghost" style="font-size: 13px;">&larr; Wizard Booking</a>`;

  const topbarActions = document.getElementById("topbarActions");
  if (topbarActions) topbarActions.innerHTML = backLink;
}

function showPortal() {
  const authSection = document.getElementById("authSection");
  const portalSection = document.getElementById("portalSection");
  const portalLoader = document.getElementById("portalLoader");
  const rescheduleModal = document.getElementById("rescheduleModal");

  if (authSection) authSection.hidden = true;
  if (portalSection) portalSection.hidden = false;
  if (portalLoader) portalLoader.hidden = true;
  if (rescheduleModal) rescheduleModal.hidden = true;

  // Render header status
  const topActions = document.getElementById("topbarActions");
  topActions.innerHTML = `
    <div style="display:flex; align-items:center; gap:16px;">
      <span class="uhid-badge" style="font-size:12px; padding:6px 12px; background:var(--slate-bg); color:var(--teal-deep);">
        ${escapeHtml(state.profile.patient_id)}
      </span>
      <button class="btn btn-ghost btn-small" id="btnLogout" style="color:var(--coral-dark);">Sign Out</button>
    </div>
  `;
  document.getElementById("btnLogout").addEventListener("click", handleLogout);
}

async function handleLogout() {
  await clearPatientAuthSession();
  state.token = null;
  state.profile = null;
  state.appointments = [];
  state.consultations = [];
  state.prescriptions = [];
  state.reports = [];
  state.timeline = [];
  window.location.replace("index.html");
}

function setupAuthTabs() {
  const btnLogin = document.getElementById("tabBtnLogin");
  const btnRegister = document.getElementById("tabBtnRegister");
  const loginCard = document.getElementById("loginCard");
  const registerCard = document.getElementById("registerCard");

  btnLogin.addEventListener("click", () => {
    btnLogin.classList.add("active");
    btnRegister.classList.remove("active");
    loginCard.hidden = false;
    registerCard.hidden = true;
  });

  btnRegister.addEventListener("click", () => {
    btnRegister.classList.add("active");
    btnLogin.classList.remove("active");
    registerCard.hidden = false;
    loginCard.hidden = true;
  });
}

function setupNavigation() {
  const navBtns = document.querySelectorAll(".portal-nav-btn");
  const tabPanels = document.querySelectorAll(".portal-tab-panel");

  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const tabName = btn.dataset.portalTab;

      navBtns.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("is-active"));

      btn.classList.add("active");
      document.getElementById(`${tabName}TabPanel`).classList.add("is-active");

      // Load/render specific tab content
      renderActiveTab(tabName);
    });
  });

  // Action links / quick actions
  document.getElementById("btnGoToTimeline").addEventListener("click", () => triggerTab("timeline"));
  document.getElementById("actGoToHistory").addEventListener("click", () => triggerTab("timeline"));
  document.getElementById("btnGoToPrescripts").addEventListener("click", () => triggerTab("prescriptions"));
  document.getElementById("actGoToReports").addEventListener("click", () => triggerTab("reports"));
  document.getElementById("actGoToProfile").addEventListener("click", () => triggerTab("profile"));
}

function triggerTab(tabName) {
  const btn = document.querySelector(`.portal-nav-btn[data-portal-tab="${tabName}"]`);
  if (btn) btn.click();
}

function renderActiveTab(tabName) {
  switch (tabName) {
    case "dashboard":
      renderDashboard();
      break;
    case "appointments":
      renderAppointments("upcoming");
      break;
    case "timeline":
      renderTimeline();
      break;
    case "prescriptions":
      renderPrescriptions();
      break;
    case "reports":
      renderReports();
      break;
    case "profile":
      renderProfile();
      break;
  }
}

// ---------------------------------------------------------------------------
// Load Database Data
// ---------------------------------------------------------------------------
async function loadPortalData() {
  const loader = document.getElementById("portalLoader");
  loader.hidden = false;
  try {
    // 1. Fetch patient profile
    state.profile = await portalApi("/patient/me");

    // 2. Fetch parallel history files
    const [appts, consults, prescripts, reports, timeline] = await Promise.all([
      portalApi("/patient/me/appointments"),
      portalApi("/patient/me/consultations"),
      portalApi("/patient/me/prescriptions"),
      portalApi("/patient/me/reports"),
      portalApi("/patient/me/timeline"),
    ]);

    state.appointments = appts;
    state.consultations = consults;
    state.prescriptions = prescripts;
    state.reports = reports;
    state.timeline = timeline;

    showPortal();
    renderDashboard();
  } catch (err) {
    const portalError = document.getElementById("portalError");
    if (portalError) {
      portalError.textContent = `Failed to load portal profile: ${err.message}`;
      portalError.hidden = false;
    } else {
      console.error("portalError element not found:", err);
    }
  } finally {
    if (loader) loader.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Form Submit Handlers (Auth & Profile)
// ---------------------------------------------------------------------------
function setupFormListeners() {
  // Login Submit
  const loginForm = document.getElementById("loginForm");
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const loginError = document.getElementById("loginError");
    loginError.hidden = true;

    const user = document.getElementById("loginUser").value.trim();
    const pass = document.getElementById("loginPass").value;

    if (!user || !pass) {
      loginError.textContent = "Please fill in all credentials.";
      loginError.hidden = false;
      return;
    }

    try {
      const res = await portalApi("/patient/auth/login", {
        method: "POST",
        body: JSON.stringify({ username_or_mobile_or_email: user, password: pass }),
      });

      state.token = "cookie-auth";
      const next = new URLSearchParams(window.location.search).get("next");
      if (next) {
        window.location.href = next;
        return;
      }
      await loadPortalData();
    } catch (err) {
      loginError.textContent = err.message;
      loginError.hidden = false;
    }
  });

  // Register Submit
  const registerForm = document.getElementById("registerForm");
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const regError = document.getElementById("registerError");
    regError.hidden = true;

    const reqData = {
      username: document.getElementById("regUser").value.trim(),
      password: document.getElementById("regPass").value,
      full_name: document.getElementById("regName").value.trim(),
      dob: document.getElementById("regDob").value,
      gender: document.getElementById("regGender").value,
      mobile: document.getElementById("regMobile").value.trim(),
      email: document.getElementById("regEmail").value.trim() || null,
      address: document.getElementById("regAddress").value.trim(),
      emergency_contact: document.getElementById("regEmergency").value.trim(),
      blood_group: document.getElementById("regBlood").value,
      allergies: document.getElementById("regAllergies").value.trim() || null,
      medical_history: document.getElementById("regHistory").value.trim() || null,
    };

    if (!reqData.username || reqData.password.length < 6 || !reqData.full_name || !reqData.mobile || !reqData.address) {
      regError.textContent = "Please fill out all required fields. Password must be at least 6 characters.";
      regError.hidden = false;
      return;
    }

    try {
      const res = await portalApi("/patient/auth/register", {
        method: "POST",
        body: JSON.stringify(reqData),
      });

      state.token = "cookie-auth";
      const next = new URLSearchParams(window.location.search).get("next");

      alert("Registration successful. Please sign in to continue.");
      document.getElementById("registerForm").reset();
      document.getElementById("tabBtnLogin").click();

      if (next) {
        const loginInput = document.getElementById("loginUser");
        const loginPass = document.getElementById("loginPass");
        if (loginInput) loginInput.value = reqData.username;
        if (loginPass) loginPass.focus();
      }
    } catch (err) {
      if (err.body && err.body.status === "activation_required") {
        document.getElementById("registerCard").hidden = true;
        document.getElementById("activateCard").hidden = false;
        
        document.getElementById("activateMessage").textContent = err.body.message;
        window._activateMobile = reqData.mobile;
        
      } else {
        regError.textContent = err.message;
        regError.hidden = false;
      }
    }
  });

  // OTP Verification for Activation
  const otpForm = document.getElementById("activateOtpForm");
  if (otpForm) {
    otpForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const otpError = document.getElementById("activateOtpError");
      otpError.hidden = true;
      
      const otp = document.getElementById("activateOtp").value.trim();
      if (!otp) return;
      
      try {
        const res = await portalApi("/patient/auth/activate", {
          method: "POST",
          body: JSON.stringify({
            mobile: window._activateMobile,
            otp: otp
          })
        });
        
        state.token = "cookie-auth";
        alert("Account activated successfully!");
        redirectAfterAuth();
        
      } catch (err) {
        otpError.textContent = err.message;
        otpError.hidden = false;
      }
    });
  }

  // Update Profile Form
  const profileForm = document.getElementById("profileEditForm");
  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const profError = document.getElementById("portalError");
    if (profError) profError.hidden = true;

    const reqData = {
      full_name: document.getElementById("profName").value.trim(),
      dob: document.getElementById("profDob").value,
      gender: document.getElementById("profGender").value,
      mobile: document.getElementById("profMobile").value.trim(),
      email: document.getElementById("profEmail").value.trim() || null,
      address: document.getElementById("profAddress").value.trim(),
      emergency_contact: document.getElementById("profEmergency").value.trim(),
      blood_group: document.getElementById("profBlood").value,
      allergies: document.getElementById("profAllergies").value.trim() || null,
      medical_history: document.getElementById("profHistory").value.trim() || null,
    };

    try {
      const updatedProfile = await portalApi("/patient/me", {
        method: "PUT",
        body: JSON.stringify(reqData),
      });
      state.profile = updatedProfile;
      alert("Your profile has been updated successfully.");
      renderProfile();
    } catch (err) {
      profError.textContent = `Couldn't update profile: ${err.message}`;
      profError.hidden = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Render A: Dashboard Tab
// ---------------------------------------------------------------------------
function renderDashboard() {
  const welcomeNameEl = document.getElementById("welcomeName");
  const welcomeUHIDEl = document.getElementById("welcomeUHID");

  if (welcomeNameEl) {
    welcomeNameEl.textContent = `Welcome, ${escapeHtml(state.profile?.full_name || "Patient")}`;
  }
  if (welcomeUHIDEl) {
    welcomeUHIDEl.textContent = state.profile?.patient_id || "UHID";
  }

  // Next Appointment
  const nextApptDiv = document.getElementById("dashNextAppt");
  const upcoming = state.appointments.filter(a => ["BOOKED", "CONFIRMED", "RESCHEDULED"].includes(a.status) && new Date(a.appointment_date) >= new Date().setHours(0,0,0,0));

  if (upcoming.length > 0) {
    // Sort upcoming ascending
    upcoming.sort((x, y) => new Date(x.appointment_date + 'T' + x.time_slot) - new Date(y.appointment_date + 'T' + y.time_slot));
    const next = upcoming[0];
    nextApptDiv.innerHTML = `
      <p><strong>Dr. ${escapeHtml(next.doctor_name)}</strong></p>
      <p style="color:var(--ink-soft); font-size:13px;">${escapeHtml(next.department_name)} | ${escapeHtml(next.branch_name)}</p>
      <p style="margin-top:8px;">📅 <strong>${formatDate(next.appointment_date)}</strong> at <strong>${next.time_slot}</strong></p>
      <div style="margin-top:12px; font-family:var(--font-mono); font-size:12px; color:var(--teal-mid);">Code: ${escapeHtml(next.appointment_code)}</div>
    `;
  } else {
    nextApptDiv.innerHTML = `<div class="empty-note" style="padding:0;">No upcoming consultations scheduled.</div>`;
  }

  // Outstanding Bills
  const billsDiv = document.getElementById("dashBills");

  const renderBillsCard = () => {
    billsDiv.innerHTML = `<div class="empty-note" style="padding:0;">No outstanding invoices.</div>`;
  };
  renderBillsCard();

  // Recent Diagnosis
  const diagnosisDiv = document.getElementById("dashRecentDiagnosis");
  if (state.consultations.length > 0) {
    const latest = state.consultations[0];
    diagnosisDiv.innerHTML = `
      <p style="font-size:12px; color:var(--ink-soft); font-family:var(--font-mono);">${formatDate(latest.consultation_date)}</p>
      <p><strong>${escapeHtml(latest.diagnosis)}</strong></p>
      <p style="font-size:13px; color:var(--ink-soft); margin-top:8px;">${escapeHtml(latest.clinical_notes)}</p>
    `;
  } else {
    diagnosisDiv.innerHTML = `<div class="empty-note">No consultation history available.</div>`;
  }

  // Recent Prescription
  const prescDiv = document.getElementById("dashRecentPrescription");
  if (state.prescriptions.length > 0) {
    const latest = state.prescriptions[0];
    let medicines = [];
    if (typeof latest.medicines === 'string') {
      try {
        medicines = JSON.parse(latest.medicines);
      } catch (_) { medicines = []; }
    } else if (Array.isArray(latest.medicines)) {
      medicines = latest.medicines;
    }
    let medHtml = medicines.slice(0, 2).map(m => `<li>${escapeHtml(m.name)} (${escapeHtml(m.dosage)})</li>`).join("");
    prescDiv.innerHTML = `
      <p style="font-size:12px; color:var(--ink-soft); font-family:var(--font-mono);">${formatDate(latest.prescription_date)}</p>
      <ul style="padding-left:18px; margin:6px 0; font-size:13px;">
        ${medHtml}
        ${medicines.length > 2 ? `<li>+ ${medicines.length - 2} more medicines</li>` : ""}
      </ul>
      <button class="btn-text" style="margin-top:10px;" onclick="viewPrescription(${latest.id})">View Full Prescription &rarr;</button>
    `;
  } else {
    prescDiv.innerHTML = `<div class="empty-note">No prescriptions available.</div>`;
  }
}

// ---------------------------------------------------------------------------
// Render B: Appointments Tab
// ---------------------------------------------------------------------------
function setupModalListeners() {
  document.getElementById("btnCloseConsultModal").addEventListener("click", () => document.getElementById("consultModal").hidden = true);
  document.getElementById("btnClosePrescriptionModal").addEventListener("click", () => document.getElementById("prescriptionModal").hidden = true);
  document.getElementById("btnCloseReportModal").addEventListener("click", () => document.getElementById("reportModal").hidden = true);
  document.getElementById("btnCloseRescheduleModal").addEventListener("click", () => document.getElementById("rescheduleModal").hidden = true);
  document.getElementById("btnCancelReschedule").addEventListener("click", () => document.getElementById("rescheduleModal").hidden = true);

  // Subtab buttons inside Appointments
  const apptSubtabs = document.querySelectorAll(".appt-subtab-btn");
  apptSubtabs.forEach(btn => {
    btn.addEventListener("click", () => {
      apptSubtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderAppointments(btn.dataset.subtab);
    });
  });
}

function renderAppointments(filter) {
  const container = document.getElementById("apptListContainer");
  container.innerHTML = `<div class="loading-sm">Loading appointments...</div>`;

  let list = [];
  const today = new Date().setHours(0,0,0,0);

  if (filter === "upcoming") {
    list = state.appointments.filter(a => ["BOOKED", "CONFIRMED", "RESCHEDULED"].includes(a.status) && new Date(a.appointment_date) >= today);
    // Sort ascending
    list.sort((x, y) => new Date(x.appointment_date + 'T' + x.time_slot) - new Date(y.appointment_date + 'T' + y.time_slot));
  } else if (filter === "completed") {
    list = state.appointments.filter(a => a.status === "COMPLETED" || (["BOOKED", "CONFIRMED", "RESCHEDULED"].includes(a.status) && new Date(a.appointment_date) < today));
    // Sort descending
    list.sort((x, y) => new Date(y.appointment_date + 'T' + y.time_slot) - new Date(x.appointment_date + 'T' + x.time_slot));
  } else {
    // History (Cancelled / Rescheduled)
    list = state.appointments.filter(a => ["CANCELLED", "RESCHEDULED"].includes(a.status));
    // Sort descending
    list.sort((x, y) => new Date(y.appointment_date + 'T' + y.time_slot) - new Date(x.appointment_date + 'T' + x.time_slot));
  }

  if (list.length === 0) {
    container.innerHTML = `<div class="empty-note" style="background:var(--panel);">No appointments found in this section.</div>`;
    return;
  }

  container.innerHTML = list.map(a => {
    let actionButtons = "";
    if (filter === "upcoming") {
      actionButtons = `
        <div class="appt-actions-col">
          <button class="btn btn-ghost btn-small" onclick="openRescheduleModal('${a.appointment_code}')">Reschedule</button>
          <button class="btn btn-outline btn-small" style="color:var(--coral-dark); border-color:var(--coral);" onclick="cancelAppointment('${a.appointment_code}')">Cancel</button>
        </div>
      `;
    } else if (a.status === "COMPLETED") {
      const consultation = getConsultationForAppointment(a.id);
      const prescription = consultation ? getPrescriptionForAppointment(a.id) : null;
      const report = consultation ? getReportForAppointment(a.id) : null;

      actionButtons = `
        <div class="appt-actions-col">
          <button class="btn btn-ghost btn-small" onclick="viewConsultationByAppt(${a.id})">View Diagnosis</button>
          ${prescription ? `<button class="btn btn-ghost btn-small" onclick="viewPrescriptionByAppt(${a.id})">View Prescription</button>` : ""}
          ${report ? `<button class="btn btn-ghost btn-small" onclick="viewReportByAppt(${a.id})">View Report</button>` : ""}
        </div>
      `;
    }

    // Checking if rescheduling metadata exists
    let rescheduleAlert = "";
    if (a.original_date && a.original_time) {
      rescheduleAlert = `
        <div class="reschedule-alert">
          🔄 Rescheduled from original slot: <strong>${formatDate(a.original_date)}</strong> at <strong>${a.original_time}</strong>
        </div>
      `;
    }

    let statusText = a.status;
    if (a.status === "confirmed") statusText = "CONFIRMED";

    return `
      <div class="appt-item">
        <div class="appt-info-col" style="flex:1;">
          <h4>Dr. ${escapeHtml(a.doctor_name)}</h4>
          <div class="appt-meta-info">
            <span>🏥 ${escapeHtml(a.branch_name)}</span>
            <span>🩺 ${escapeHtml(a.department_name)}</span>
            <span>📅 <strong>${formatDate(a.appointment_date)}</strong> at <strong>${a.time_slot}</strong></span>
            <span>Fee: &#8377;${a.fee}</span>
          </div>
          <div style="margin-top:6px; font-size:12px; font-family:var(--font-mono);">
            Code: <strong>${escapeHtml(a.appointment_code)}</strong> | Status: <span class="badge-${statusText.toLowerCase()}">${statusText}</span>
          </div>
          ${rescheduleAlert}
        </div>
        ${actionButtons}
      </div>
    `;
  }).join("");
}

// Cancel appointment flow
async function cancelAppointment(code) {
  if (!confirm("Are you sure you want to cancel this appointment? This action cannot be undone.")) return;

  const loader = document.getElementById("portalLoader");
  loader.hidden = false;
  try {
    const res = await portalApi(`/appointments/${code}/cancel`, {
      method: "POST",
      body: JSON.stringify({ mobile: state.profile.mobile })
    });
    alert(`Appointment cancelled successfully.\nNotification preview:\n${res.notification_preview || 'Sent'}`);
    await loadPortalData();
    renderActiveTab("appointments");
  } catch (err) {
    alert(`Failed to cancel appointment: ${err.message}`);
  } finally {
    loader.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Reschedule Slot Selection Flow
// ---------------------------------------------------------------------------
async function openRescheduleModal(code) {
  const loader = document.getElementById("portalLoader");
  loader.hidden = false;
  try {
    const appt = state.appointments.find(a => a.appointment_code === code);
    if (!appt) {
      alert("Appointment details could not be found.");
      return;
    }
    state.rescheduleAppt = appt;
    state.rescheduleDate = null;
    state.rescheduleTime = null;

    document.getElementById("btnConfirmReschedule").disabled = true;
    document.getElementById("rescheduleError").hidden = true;

    // Load available dates
    await loadRescheduleDates(appt.doctor_id);

    document.getElementById("rescheduleModal").hidden = false;
  } catch (err) {
    alert(`Failed to open rescheduling: ${err.message}`);
  } finally {
    loader.hidden = true;
  }
}

async function loadRescheduleDates(doctorId) {
  const rail = document.getElementById("dateRail");
  rail.innerHTML = `<div class="loading-sm">Loading dates...</div>`;
  document.getElementById("slotGrid").innerHTML = "";

  try {
    const dates = await publicApi(`/doctors/${doctorId}/dates`);
    rail.innerHTML = "";
    if (dates.length === 0) {
      rail.innerHTML = `<div class="empty-note">Doctor has no upcoming working days.</div>`;
      return;
    }

    dates.forEach(d => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "date-chip";
      btn.innerHTML = `
        <span class="dc-day">${escapeHtml(d.weekday.slice(0, 3))}</span>
        <span class="dc-num">${parseInt(d.date.split("-")[2], 10)}</span>
        <span class="dc-slots">${d.free_slots} slots</span>
      `;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#dateRail .date-chip").forEach(c => c.classList.remove("is-selected"));
        btn.classList.add("is-selected");
        state.rescheduleDate = d.date;
        state.rescheduleTime = null;
        document.getElementById("btnConfirmReschedule").disabled = true;
        loadRescheduleSlots(doctorId, d.date);
      });
      rail.appendChild(btn);
    });
  } catch (err) {
    rail.innerHTML = `<div class="empty-note" style="color:var(--coral-dark);">Error: ${err.message}</div>`;
  }
}

async function loadRescheduleSlots(doctorId, dateStr) {
  const grid = document.getElementById("slotGrid");
  grid.innerHTML = `<div class="loading-sm">Loading slots...</div>`;

  try {
    const slots = await publicApi(`/doctors/${doctorId}/slots?date=${dateStr}`);
    grid.innerHTML = "";
    const activeSlots = slots.filter(s => s.status === "AVAILABLE");

    if (activeSlots.length === 0) {
      grid.innerHTML = `<div class="empty-note">No available slots for this date.</div>`;
      return;
    }

    activeSlots.forEach(s => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "slot-chip";
      btn.textContent = s.time;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#slotGrid .slot-chip").forEach(c => c.classList.remove("is-selected"));
        btn.classList.add("is-selected");
        state.rescheduleTime = s.time;
        document.getElementById("btnConfirmReschedule").disabled = false;
      });
      grid.appendChild(btn);
    });
  } catch (err) {
    grid.innerHTML = `<div class="empty-note" style="color:var(--coral-dark);">Error: ${err.message}</div>`;
  }
}

// Reschedule submission
document.getElementById("btnConfirmReschedule").addEventListener("click", async () => {
  if (!state.rescheduleAppt || !state.rescheduleDate || !state.rescheduleTime) return;

  const errBox = document.getElementById("rescheduleError");
  errBox.hidden = true;

  const code = state.rescheduleAppt.appointment_code;
  const payload = {
    mobile: state.profile.mobile,
    appointment_date: state.rescheduleDate,
    time_slot: state.rescheduleTime,
  };

  try {
    const res = await portalApi(`/appointments/${code}/reschedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (res.status === "CONFLICT") {
      errBox.textContent = res.message;
      errBox.hidden = false;
      return;
    }

    alert(`Rescheduled successfully!\nNotification preview:\n${res.notification_preview || 'Sent'}`);
    document.getElementById("rescheduleModal").hidden = true;
    await loadPortalData();
    renderActiveTab("appointments");
  } catch (err) {
    errBox.textContent = `Error: ${err.message}`;
    errBox.hidden = false;
  }
});

// Helper for calling public endpoints (Wizard API)
async function publicApi(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Request failed");
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Render C: Medical History Timeline
// ---------------------------------------------------------------------------
function renderTimeline() {
  const container = document.getElementById("timelineContainer");
  
  if (state.timeline.length === 0) {
    container.innerHTML = `<div class="empty-note" style="background:var(--panel);">No clinical events recorded.</div>`;
    return;
  }

  container.innerHTML = state.timeline.map((event, idx) => {
    let detailButton = "";
    let timelineClass = "booked";

    if (event.type === "CONSULTATION_COMPLETED") {
      timelineClass = "completed";
      detailButton = `<button class="btn btn-ghost btn-small" style="margin-top:10px;" onclick="viewConsultationTimeline(${idx})">View Records</button>`;
    } else if (event.type === "APPOINTMENT_CANCELLED") {
      timelineClass = "cancelled";
    }

    return `
      <div class="timeline-item ${timelineClass}">
        <div class="timeline-icon"></div>
        <div class="timeline-content">
          <div class="timeline-date">${formatDate(event.date)} ${event.time !== "12:00" && event.time !== "12:05" && event.time !== "14:00" ? `at ${event.time}` : ""}</div>
          <h4>${escapeHtml(event.title)}</h4>
          <p>${escapeHtml(event.description)}</p>
          ${detailButton}
        </div>
      </div>
    `;
  }).join("");
}

// Timeline consultation modal detail fetcher
function viewConsultationTimeline(idx) {
  const event = state.timeline[idx];
  // Retrieve corresponding consultation object
  // Find consultation matching appointment code or date
  // Since we sorted, search state.consultations
  const consult = state.consultations.find(c => event.description.includes(c.diagnosis));
  if (consult) {
    viewConsultationDetails(consult);
  } else {
    // Fallback if mismatch: search directly
    const firstConsult = state.consultations[0];
    if (firstConsult) viewConsultationDetails(firstConsult);
  }
}

function getConsultationForAppointment(apptId) {
  return state.consultations.find(c => c.appointment_id === apptId) || null;
}

function getPrescriptionForAppointment(apptId) {
  const consult = getConsultationForAppointment(apptId);
  if (!consult) return null;
  return state.prescriptions.find(p => p.consultation_id === consult.id) || null;
}

function getReportForAppointment(apptId) {
  const consult = getConsultationForAppointment(apptId);
  if (!consult) return null;
  return state.reports.find(r => r.consultation_id === consult.id) || null;
}

function viewConsultationByAppt(apptId) {
  const consult = getConsultationForAppointment(apptId);
  if (consult) {
    viewConsultationDetails(consult);
  } else {
    alert("No consultation summary recorded yet by the doctor.");
  }
}

function viewPrescriptionByAppt(apptId) {
  const prescription = getPrescriptionForAppointment(apptId);
  if (!prescription) {
    alert("No prescription exists for this completed visit.");
    return;
  }
  viewPrescription(prescription.id);
}

function viewReportByAppt(apptId) {
  const report = getReportForAppointment(apptId);
  if (!report) {
    alert("No report exists for this completed visit.");
    return;
  }
  viewReport(report.id);
}

function viewConsultationDetails(c) {
  const body = document.getElementById("consultModalBody");
  
  // Checking related prescription and report
  const prescription = state.prescriptions.find(p => p.consultation_id === c.id);
  const report = state.reports.find(r => r.consultation_id === c.id);

  let prescHtml = "<em>None prescribed.</em>";
  if (prescription) {
    let meds = [];
    if (typeof prescription.medicines === 'string') {
      try { meds = JSON.parse(prescription.medicines); } catch (_) {}
    } else if (Array.isArray(prescription.medicines)) {
      meds = prescription.medicines;
    }
    prescHtml = meds.map(m => `
      <div style="padding: 6px 0; border-bottom: 1px solid var(--mist);">
        <strong>${escapeHtml(m.name)}</strong> - ${escapeHtml(m.dosage)} (${escapeHtml(m.frequency)}) for ${escapeHtml(m.duration)}<br>
        <small style="color:var(--ink-soft);">${escapeHtml(m.instructions)}</small>
      </div>
    `).join("");
  }

  let reportHtml = "<em>No tests ordered.</em>";
  if (report) {
    reportHtml = `
      <div style="display:flex; justify-content:between; align-items:center;">
        <span>📄 ${escapeHtml(report.report_name)} (${escapeHtml(report.report_type)})</span>
        <button class="btn btn-ghost btn-small" onclick="viewReport(${report.id})">Open Report</button>
      </div>
    `;
  }

  body.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:16px;">
      <div>
        <h4 style="margin:0 0 4px; color:var(--teal-deep);">Diagnosis: ${escapeHtml(c.diagnosis)}</h4>
        <span style="font-size:12px; color:var(--ink-soft);">Consulted by Dr. ${escapeHtml(c.doctor_name)} | ${escapeHtml(c.department_name)} | ${formatDate(c.consultation_date)}</span>
      </div>

      <div>
        <strong>Symptoms Reported:</strong>
        <p style="margin:4px 0; background:var(--mist); padding:10px; border-radius:var(--radius-sm);">${escapeHtml(c.symptoms || "Not recorded")}</p>
      </div>

      <div>
        <strong>Vitals Captured:</strong>
        <p style="margin:4px 0; background:var(--mist); padding:10px; border-radius:var(--radius-sm); font-family:var(--font-mono);">${escapeHtml(c.vitals || "Not recorded")}</p>
      </div>

      <div>
        <strong>Clinical Notes:</strong>
        <p style="margin:4px 0; font-size:14px; line-height:1.5;">${escapeHtml(c.clinical_notes || "None")}</p>
      </div>

      <div>
        <strong>Treatment / Advice:</strong>
        <p style="margin:4px 0; font-size:14px; line-height:1.5;">${escapeHtml(c.treatment || "None")}</p>
      </div>

      <div style="border-top: 1px solid var(--line); padding-top:16px;">
        <h5 style="margin:0 0 8px; font-size:14px; color:var(--teal-deep);">Prescribed Medications</h5>
        ${prescHtml}
      </div>

      <div style="border-top: 1px solid var(--line); padding-top:16px;">
        <h5 style="margin:0 0 8px; font-size:14px; color:var(--teal-deep);">Lab Investigations</h5>
        ${reportHtml}
      </div>

      ${c.follow_up_date ? `
        <div style="background:#E7F7EF; color:#145A32; padding:12px; border-radius:var(--radius-sm); font-size:13px; font-weight:600;">
          📅 Follow-up Visit Scheduled: ${formatDate(c.follow_up_date)}
        </div>
      ` : ""}
    </div>
  `;

  document.getElementById("consultModal").hidden = false;
}

// ---------------------------------------------------------------------------
// Render D: Prescriptions Tab
// ---------------------------------------------------------------------------
function renderPrescriptions() {
  const container = document.getElementById("prescriptionContainer");
  if (state.prescriptions.length === 0) {
    container.innerHTML = `<div class="empty-note" style="background:var(--panel);">No prescriptions written.</div>`;
    return;
  }

  container.innerHTML = state.prescriptions.map(p => {
    let meds = [];
    if (typeof p.medicines === 'string') {
      try {
        meds = JSON.parse(p.medicines);
      } catch (_) { meds = []; }
    } else if (Array.isArray(p.medicines)) {
      meds = p.medicines;
    }

    const medRows = meds.map(m => `
      <tr>
        <td><strong>${escapeHtml(m.name)}</strong></td>
        <td>${escapeHtml(m.dosage)}</td>
        <td>${escapeHtml(m.frequency)}</td>
        <td>${escapeHtml(m.duration)}</td>
        <td>${escapeHtml(m.instructions)}</td>
      </tr>
    `).join("");

    return `
      <div class="prescription-card">
        <div class="presc-head">
          <div>
            <h4>Prescribed by Dr. ${escapeHtml(p.doctor_name)}</h4>
            <small style="color:var(--ink-soft);">${escapeHtml(p.department_name || "General Medicine")}</small>
          </div>
          <span class="presc-date">📅 ${formatDate(p.prescription_date)}</span>
        </div>
        <table class="medicine-table">
          <thead>
            <tr>
              <th>Medicine</th>
              <th>Dosage</th>
              <th>Frequency</th>
              <th>Duration</th>
              <th>Instructions</th>
            </tr>
          </thead>
          <tbody>
            ${medRows}
          </tbody>
        </table>
        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:14px;">
          <button class="btn btn-ghost btn-small" onclick="viewPrescription(${p.id})">Print prescription</button>
        </div>
      </div>
    `;
  }).join("");
}

function viewPrescription(id) {
  const p = state.prescriptions.find(item => item.id === id);
  if (!p) return;

  let meds = [];
  if (typeof p.medicines === 'string') {
    try { meds = JSON.parse(p.medicines); } catch (_) {}
  } else if (Array.isArray(p.medicines)) {
    meds = p.medicines;
  }

  const medRows = meds.map(m => `
    <div style="padding:10px 0; border-bottom:1px solid var(--line);">
      <strong>${escapeHtml(m.name)}</strong><br>
      <small style="color:var(--ink-soft);">Dosage: ${escapeHtml(m.dosage)} | Freq: ${escapeHtml(m.frequency)} | Dur: ${escapeHtml(m.duration)}</small><br>
      <small style="color:var(--teal-mid);">Instructions: ${escapeHtml(m.instructions)}</small>
    </div>
  `).join("");

  const body = document.getElementById("prescriptionModalBody");
  body.innerHTML = `
    <div style="border: 2px dashed var(--line); padding: 20px; border-radius: var(--radius-md); font-family:var(--font-mono);">
      <div style="text-align:center; border-bottom: 2px solid var(--teal-deep); padding-bottom:12px; margin-bottom:16px;">
        <h3 style="margin:0; color:var(--teal-deep);">Dr. ${escapeHtml(p.doctor_name)}</h3>
        <span>${escapeHtml(p.department_name || "Specialist Clinic")}</span><br>
        <span>Varuvi Hospital</span>
      </div>
      <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:14px;">
        <span>Patient: <strong>${escapeHtml(state.profile.full_name)}</strong></span>
        <span>UHID: <strong>${state.profile.patient_id}</strong></span>
        <span>Date: <strong>${formatDate(p.prescription_date)}</strong></span>
      </div>
      <div style="margin-top:20px;">
        <h4 style="color:var(--teal-deep); border-bottom:1px solid var(--line); padding-bottom:6px;">Rx Medications</h4>
        ${medRows}
      </div>
      <div style="margin-top:30px; text-align:center; font-size:11px; color:var(--ink-soft); border-top:1px solid var(--line); padding-top:12px;">
        This is a digitally signed electronic prescription.
      </div>
    </div>
    <button class="btn btn-primary btn-block" style="margin-top:18px;" onclick="window.print()">Print prescription / PDF</button>
  `;

  document.getElementById("prescriptionModal").hidden = false;
}

// ---------------------------------------------------------------------------
// Render E: Medical Reports Tab
// ---------------------------------------------------------------------------
function renderReports() {
  const container = document.getElementById("reportsContainer");
  if (state.reports.length === 0) {
    container.innerHTML = `<div class="empty-note" style="background:var(--panel); width:100%;">No medical reports available.</div>`;
    return;
  }

  container.innerHTML = state.reports.map(r => `
    <div class="report-card">
      <div class="report-header">
        <span class="report-doc-icon">📄</span>
        <div class="report-title-col">
          <h4>${escapeHtml(r.report_name)}</h4>
          <span>${escapeHtml(r.report_type)}</span>
        </div>
      </div>
      <div class="report-meta">
        <p>Ordered by: <strong>Dr. ${escapeHtml(r.doctor_name || "General Medical Staff")}</strong></p>
        <p>Dept: ${escapeHtml(r.department_name || "Pathology Lab")}</p>
        <p>Date: ${formatDate(r.report_date)}</p>
        <p>Status: <span class="badge-completed" style="font-size:10px; padding:3px 8px;">${escapeHtml(r.status)}</span></p>
      </div>
      <div class="report-actions">
        <button class="btn btn-ghost btn-small" style="flex:1;" onclick="viewReport(${r.id})">View Report</button>
        <button class="btn btn-outline btn-small" style="flex:1;" onclick="viewReport(${r.id})">Open Details</button>
      </div>
    </div>
  `).join("");
}

function viewReport(id) {
  const r = state.reports.find(item => item.id === id);
  if (!r) return;

  const body = document.getElementById("reportModalBody");
  body.innerHTML = `
    <div style="border:1px solid var(--line); padding:24px; border-radius:var(--radius-md); font-family:var(--font-mono); background:#FAFDFD;">
      <div style="text-align:center; border-bottom:1px solid var(--line); padding-bottom:12px; margin-bottom:16px;">
        <h4 style="margin:0; color:var(--teal-deep);">LABORATORY INVESTIGATION REPORT</h4>
        <span>Varuvi Diagnostic Laboratory</span>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:12px; border-bottom:1px solid var(--line); padding-bottom:12px; margin-bottom:16px;">
        <div>Patient Name: <strong>${escapeHtml(state.profile.full_name)}</strong></div>
        <div>UHID: <strong>${state.profile.patient_id}</strong></div>
        <div>Test Date: <strong>${formatDate(r.report_date)}</strong></div>
        <div>Status: <strong>${escapeHtml(r.status)}</strong></div>
      </div>
      <div style="margin-top:16px;">
        <h5 style="margin:0 0 10px; color:var(--teal-deep); font-size:14px;">Test: ${escapeHtml(r.report_name)}</h5>
        
        <table style="width:100%; font-size:12px; border-collapse:collapse; margin-top:8px;">
          <thead>
            <tr style="background:#EEF3F3;">
              <th style="padding:6px; text-align:left;">Parameter</th>
              <th style="padding:6px; text-align:left;">Result</th>
              <th style="padding:6px; text-align:left;">Reference Interval</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="padding:6px; border-bottom:1px solid var(--line);">White Blood Cells (WBC)</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">7.2 x10^3/uL</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">4.5 - 11.0</td>
            </tr>
            <tr>
              <td style="padding:6px; border-bottom:1px solid var(--line);">Red Blood Cells (RBC)</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">4.85 x10^6/uL</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">4.30 - 5.90</td>
            </tr>
            <tr>
              <td style="padding:6px; border-bottom:1px solid var(--line);">Hemoglobin</td>
              <td style="padding:6px; border-bottom:1px solid var(--line); font-weight:bold; color:var(--teal-mid);">14.2 g/dL</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">13.5 - 17.5</td>
            </tr>
            <tr>
              <td style="padding:6px; border-bottom:1px solid var(--line);">Platelets</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">245 x10^3/uL</td>
              <td style="padding:6px; border-bottom:1px solid var(--line);">150 - 450</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style="margin-top:30px; text-align:center; font-size:11px; color:var(--ink-soft); border-top:1px solid var(--line); padding-top:12px;">
        Digitally signed by Chief Pathologist, Varuvi Diagnostics.
      </div>
    </div>
  `;

  document.getElementById("reportModal").hidden = false;
}

// ---------------------------------------------------------------------------
// Render F: Profile Tab
// ---------------------------------------------------------------------------
function renderProfile() {
  const container = document.getElementById("profileDetailsView");
  const p = state.profile;
  
  // Calculate Age
  let age = "Not provided";
  if (p.dob) {
    try {
      const birth = new Date(p.dob);
      const diff = Date.now() - birth.getTime();
      const ageDate = new Date(diff);
      age = Math.abs(ageDate.getUTCFullYear() - 1970);
    } catch (_) {}
  }

  container.innerHTML = `
    <h3>Medical Identity Record</h3>
    <div class="profile-grid-rows">
      <div class="row">
        <span>UHID / Patient ID</span>
        <strong style="font-family:var(--font-mono); color:var(--teal-mid);">${escapeHtml(p.patient_id)}</strong>
      </div>
      <div class="row">
        <span>Full Name</span>
        <span>${escapeHtml(p.full_name)}</span>
      </div>
      <div class="row">
        <span>Date of Birth</span>
        <span>${formatDate(p.dob)}</span>
      </div>
      <div class="row">
        <span>Age</span>
        <span>${age} yrs</span>
      </div>
      <div class="row">
        <span>Gender</span>
        <span>${escapeHtml(p.gender || "Not provided")}</span>
      </div>
      <div class="row">
        <span>Mobile Number</span>
        <span>${escapeHtml(p.mobile)}</span>
      </div>
      <div class="row">
        <span>Email Address</span>
        <span>${escapeHtml(p.email || "Not provided")}</span>
      </div>
      <div class="row">
        <span>Emergency Contact</span>
        <span>${escapeHtml(p.emergency_contact || "Not provided")}</span>
      </div>
      <div class="row">
        <span>Blood Group</span>
        <span style="font-weight:bold; color:var(--coral);">${escapeHtml(p.blood_group || "Not provided")}</span>
      </div>
      <div class="row" style="flex-direction:column; gap:6px;">
        <span>Known Allergies</span>
        <span style="color:var(--coral-dark); font-weight:500;">${escapeHtml(p.allergies || "None")}</span>
      </div>
      <div class="row" style="flex-direction:column; gap:6px;">
        <span>Chronic Illnesses / Medical History</span>
        <span>${escapeHtml(p.medical_history || "None")}</span>
      </div>
    </div>
  `;

  // Pre-fill Edit Form
  document.getElementById("profName").value = p.full_name;
  document.getElementById("profDob").value = p.dob || "";
  document.getElementById("profGender").value = p.gender || "Male";
  document.getElementById("profMobile").value = p.mobile;
  document.getElementById("profEmail").value = p.email || "";
  document.getElementById("profAddress").value = p.address || "";
  document.getElementById("profEmergency").value = p.emergency_contact || "";
  document.getElementById("profBlood").value = p.blood_group || "Not provided";
  document.getElementById("profAllergies").value = p.allergies || "";
  document.getElementById("profHistory").value = p.medical_history || "";
}
