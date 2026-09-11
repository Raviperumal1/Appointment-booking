/* ==========================================================================
   Varuvi — Modern SaaS Booking Wizard Logic
   Talks to the FastAPI backend (localhost:8000 by default).
   ========================================================================== */

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "http://localhost:8000" : "";
const TOTAL_STEPS = 6;

async function checkPatientAuth() {
  try {
    const res = await fetch(`${API_BASE}/patient/auth/session`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    return res.ok;
  } catch (_) {
    return false;
  }
}

const state = {
  step: 1,
  patient: { name: "", age: "", gender: "", mobile: "", email: "", address: "", reason: "" },
  branch: null,      // {id, name, address, phone}
  department: null,
  doctor: null,
  date: null,        // 'YYYY-MM-DD'
  dateMeta: null,    // {weekday, free_slots, ...}
  time: null,        // 'HH:MM'
  booking: null,     // API response after confirmation
};

async function hasPatientAuth() {
  return await checkPatientAuth();
}

function showBookingPage() {
  const landingHero = document.getElementById("landingHero");
  const bookingApp = document.getElementById("bookingApp");

  if (bookingApp) {
    if (landingHero) landingHero.hidden = true;
    bookingApp.hidden = false;
    window.location.hash = "booking";
    return;
  }

  if (!window.location.pathname.endsWith("/booking.html")) {
    window.location.href = "booking.html";
  }
}

function showLandingPage() {
  const landingHero = document.getElementById("landingHero");
  const bookingApp = document.getElementById("bookingApp");
  if (landingHero) landingHero.hidden = false;
  if (bookingApp) bookingApp.hidden = true;
  window.location.hash = "";
}

async function fillAuthenticatedPatientDetails() {
  if (!(await hasPatientAuth())) return;

  try {
    const res = await fetch(`${API_BASE}/patient/me`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });

    if (!res.ok) return;
    const profile = await res.json();

    const nameInput = document.getElementById("patientName");
    const mobileInput = document.getElementById("patientMobile");
    const emailInput = document.getElementById("patientEmail");
    const addressInput = document.getElementById("patientAddress");

    if (nameInput && profile.full_name) nameInput.value = profile.full_name;
    if (mobileInput) {
      mobileInput.value = profile.mobile || "";
      mobileInput.disabled = true;
      mobileInput.setAttribute("aria-readonly", "true");
    }
    if (emailInput) {
      emailInput.value = profile.email || "";
      emailInput.disabled = true;
      emailInput.setAttribute("aria-readonly", "true");
    }
    if (addressInput) {
      addressInput.value = profile.address || "";
      addressInput.disabled = true;
      addressInput.setAttribute("aria-readonly", "true");
    }
  } catch (err) {
    console.warn("Could not preload patient profile for booking form:", err);
  }
}

async function handleBookAppointmentClick() {
  const bookingTarget = new URL("booking.html", window.location.href).toString();

  if (await hasPatientAuth()) {
    window.location.href = bookingTarget;
    return;
  }

  const patientLoginUrl = new URL("patient.html", window.location.href);
  patientLoginUrl.searchParams.set("next", bookingTarget);
  window.location.href = patientLoginUrl.toString();
}

// ---------------------------------------------------------------------------
// Fetch Helper
// ---------------------------------------------------------------------------

async function api(path, options) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const detail = (body && body.detail) ? body.detail : `Request failed (${res.status})`;
    throw new Error(detail);
  }
  return body;
}

// ---------------------------------------------------------------------------
// Stepper Logic
// ---------------------------------------------------------------------------

function renderStepper() {
  const pct = ((state.step - 1) / (TOTAL_STEPS - 1)) * 100;
  document.getElementById("stepperFill").style.width = `${pct}%`;

  document.querySelectorAll("#stepperDots li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.classList.remove("done", "current");
    if (n < state.step) li.classList.add("done");
    if (n === state.step) li.classList.add("current");
  });
}

const cancelBookingBtn = document.getElementById("cancelBooking");
const nextBranchBtn = document.getElementById("toStep3");
const nextDepartmentBtn = document.getElementById("toStep4");
const nextDoctorBtn = document.getElementById("toStep5");

function syncStepButtons() {
  if (nextBranchBtn) nextBranchBtn.disabled = !state.branch;
  if (nextDepartmentBtn) nextDepartmentBtn.disabled = !state.department;
  if (nextDoctorBtn) nextDoctorBtn.disabled = !state.doctor;
}

function goToStep(n) {
  state.step = n;
  document.querySelectorAll(".step-panel").forEach((panel) => {
    panel.classList.toggle("is-active", Number(panel.dataset.panel) === n);
  });
  renderStepper();
  syncStepButtons();
  if (cancelBookingBtn) cancelBookingBtn.hidden = !(n === 6 && state.booking);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll("[data-back]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (state.step > 1) goToStep(state.step - 1);
  });
});

if (nextBranchBtn) {
  nextBranchBtn.addEventListener("click", () => {
    if (!state.branch) return;
    loadDepartments(state.branch.id);
    goToStep(3);
  });
}

if (nextDepartmentBtn) {
  nextDepartmentBtn.addEventListener("click", () => {
    if (!state.department || !state.branch) return;
    loadDoctors(state.branch.id, state.department.id);
    goToStep(4);
  });
}

if (nextDoctorBtn) {
  nextDoctorBtn.addEventListener("click", () => {
    if (!state.doctor) return;
    loadDates(state.doctor.id);
    goToStep(5);
  });
}

// ---------------------------------------------------------------------------
// STEP 1 — Patient Validation
// ---------------------------------------------------------------------------

function validatePatientForm() {
  let ok = true;
  const name = document.getElementById("patientName").value.trim();
  const age = document.getElementById("patientAge").value.trim();
  const mobile = document.getElementById("patientMobile").value.trim();
  const symptoms = document.getElementById("patientReason").value.trim();

  const setError = (id, msg) => {
    const el = document.getElementById(`err-${id}`);
    if (el) el.textContent = msg || "";
  };

  if (!name) { setError("patientName", "Please enter the patient's full name."); ok = false; }
  else setError("patientName", "");

  const normalizedAge = Number(age);
  if (!age || !Number.isInteger(normalizedAge) || normalizedAge < 1 || normalizedAge > 120) {
    setError("patientAge", "Enter a valid age between 1 and 120.");
    ok = false;
  } else setError("patientAge", "");

  if (!/^\d{10}$/.test(mobile.replace(/\D/g, ""))) {
    setError("patientMobile", "Enter a valid 10-digit mobile number.");
    ok = false;
  } else setError("patientMobile", "");

  if (!symptoms) {
    alert("Please describe the patient's symptoms.");
    ok = false;
  }

  return ok;
}

const toStep2Btn = document.getElementById("toStep2");
if (toStep2Btn) {
  toStep2Btn.addEventListener("click", () => {
    if (!validatePatientForm()) return;
    state.patient = {
      name: document.getElementById("patientName").value.trim(),
      age: document.getElementById("patientAge").value.trim(),
      gender: null,
      mobile: document.getElementById("patientMobile").value.trim(),
      email: null,
      address: "",
      reason: document.getElementById("patientReason").value.trim(),
    };
    loadBranches();
    goToStep(2);
  });
}

// ---------------------------------------------------------------------------
// STEP 2 — Branches (Shows OPEN Branches Only)
// ---------------------------------------------------------------------------

async function loadBranches() {
  const list = document.getElementById("branchList");
  list.innerHTML = `<div class="loading">Loading open branches&hellip;</div>`;
  try {
    const branches = await api("/branches");
    if (!branches.length) {
      list.innerHTML = `<div class="empty-note">No open hospital branches available currently.</div>`;
      return;
    }
    list.innerHTML = "";
    branches.forEach((b) => {
      const card = document.createElement("button");
      card.className = "pick-card";
      card.type = "button";
      card.innerHTML = `
        <div>
          <div class="pc-title">${escapeHtml(b.name)}</div>
          <div class="pc-sub">${escapeHtml(b.address)}</div>
        </div>
        <div class="pc-sub" style="margin-top: 8px; font-weight: 500;">📞 ${escapeHtml(b.phone)}</div>
      `;
      card.addEventListener("click", () => selectBranch(b, card));
      list.appendChild(card);
    });
  } catch (e) {
    list.innerHTML = `<div class="empty-note" style="color: var(--coral-dark);">Couldn't reach server: ${escapeHtml(e.message)}.</div>`;
  }
}

function selectBranch(branch, cardEl) {
  state.branch = branch;
  state.department = null;
  state.doctor = null;
  state.date = null;
  state.time = null;
  document.querySelectorAll("#branchList .pick-card").forEach((c) => c.classList.remove("is-selected"));
  cardEl.classList.add("is-selected");
  document.getElementById("deptContext").textContent = `Available departments at ${branch.name}.`;
  document.getElementById("deptSuggestion").hidden = true;
  loadDepartments(branch.id);
  goToStep(3);
}

async function analyzeSymptoms(branchId) {
  if (!state.patient.reason) return null;
  try {
    return await api("/symptoms/analyze", {
      method: "POST",
      body: JSON.stringify({ symptoms: state.patient.reason, branch_id: branchId }),
    });
  } catch (e) {
    console.warn("Symptom analysis bypassed:", e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// STEP 3 — Department
// ---------------------------------------------------------------------------

async function loadDepartments(branchId) {
  const list = document.getElementById("deptList");
  const suggestionNote = document.getElementById("deptSuggestion");
  const overlay = document.getElementById("deptOverlay");

  if (overlay) overlay.hidden = false;
  list.innerHTML = `<div class="loading">Preparing departments&hellip;</div>`;
  suggestionNote.hidden = true;

  try {
    const depts = await api(`/departments?branch_id=${branchId}`);
    if (!depts.length) {
      list.innerHTML = `<div class="empty-note">No active departments available at this branch.</div>`;
      if (overlay) overlay.hidden = true;
      return;
    }

    list.innerHTML = "";
    depts.forEach((d) => {
      const card = document.createElement("button");
      card.className = "pick-card";
      card.type = "button";
      card.dataset.deptId = d.id;
      card.innerHTML = `
        <div>
          <div class="pc-title">${escapeHtml(d.name)}</div>
        </div>
      `;
      card.addEventListener("click", () => selectDepartment(d, card));
      list.appendChild(card);
    });

    const analysis = await analyzeSymptoms(branchId);
    if (analysis && analysis.department_id) {
      suggestionNote.hidden = false;
      suggestionNote.innerHTML = `<strong>🤖 AI Recommended Department:</strong> <em>${escapeHtml(analysis.department_name)}</em> &mdash; ${escapeHtml(analysis.explanation)}`;
      const recommended = depts.find((d) => d.id === analysis.department_id);
      if (recommended) {
        const recommendedCard = list.querySelector(`.pick-card[data-dept-id="${recommended.id}"]`);
        if (recommendedCard) {
          recommendedCard.classList.add("is-selected");
          selectDepartment(recommended, recommendedCard);
          if (overlay) overlay.hidden = true;
          return;
        }
      }
    }
  } catch (e) {
    list.innerHTML = `<div class="empty-note" style="color: var(--coral-dark);">Couldn't load departments: ${escapeHtml(e.message)}</div>`;
  } finally {
    if (overlay) overlay.hidden = true;
  }
}

function selectDepartment(dept, cardEl) {
  state.department = dept;
  state.doctor = null;
  state.date = null;
  state.time = null;
  document.querySelectorAll("#deptList .pick-card").forEach((c) => c.classList.remove("is-selected"));
  cardEl.classList.add("is-selected");
  document.getElementById("doctorContext").textContent =
    `${dept.name} specialists at ${state.branch.name}.`;
  loadDoctors(state.branch.id, dept.id);
  goToStep(4);
}

// ---------------------------------------------------------------------------
// STEP 4 — Doctor (Shows ACTIVE Doctors Only)
// ---------------------------------------------------------------------------

async function loadDoctors(branchId, departmentId) {
  const list = document.getElementById("doctorList");
  list.innerHTML = `<div class="loading">Loading specialists&hellip;</div>`;
  try {
    const doctors = await api(`/doctors?branch_id=${branchId}&department_id=${departmentId}`);
    if (!doctors.length) {
      list.innerHTML = `<div class="empty-note">No active specialists currently available in this department.</div>`;
      return;
    }
    list.innerHTML = "";
    doctors.forEach((doc) => {
      const card = document.createElement("button");
      card.className = "pick-card";
      card.type = "button";
      card.innerHTML = `
        <div>
          <div class="pc-title">${escapeHtml(doc.name)}</div>
          <div class="pc-sub">${escapeHtml(doc.qualification)}</div>
        </div>
      `;
      card.addEventListener("click", () => selectDoctor(doc, card));
      list.appendChild(card);
    });

    if (doctors.length === 1) {
      const single = doctors[0];
      const card = list.querySelector(".pick-card");
      if (card) {
        card.classList.add("is-selected");
        selectDoctor(single, card);
      }
    }
  } catch (e) {
    list.innerHTML = `<div class="empty-note" style="color: var(--coral-dark);">Couldn't load doctors: ${escapeHtml(e.message)}</div>`;
  }
}

function selectDoctor(doctor, cardEl) {
  state.doctor = doctor;
  state.date = null;
  state.time = null;
  document.querySelectorAll("#doctorList .pick-card").forEach((c) => c.classList.remove("is-selected"));
  if (cardEl) cardEl.classList.add("is-selected");
  document.getElementById("slotContext").textContent =
    `${doctor.name} • ${state.department.name} • ${state.branch.name}`;
  hideConflict();
  hideSummary();
  loadDates(doctor.id);
  goToStep(5);
}

// ---------------------------------------------------------------------------
// STEP 5 — Dates & Slots
// ---------------------------------------------------------------------------

async function loadDates(doctorId) {
  const rail = document.getElementById("dateRail");
  rail.innerHTML = `<div class="loading">Finding open dates&hellip;</div>`;
  document.getElementById("slotGrid").innerHTML = "";
  try {
    const dates = await api(`/doctors/${doctorId}/dates?days=14`);
    if (!dates.length) {
      rail.innerHTML = `<div class="empty-note">This doctor has no upcoming availability.</div>`;
      return;
    }
    rail.innerHTML = "";
    dates.forEach((d, idx) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "date-chip" + (d.full ? " is-full" : "");
      const dt = new Date(d.date + "T00:00:00");
      chip.innerHTML = `
        <div class="dc-day">${d.weekday.slice(0, 3)}</div>
        <div class="dc-date">${dt.getDate()}/${dt.getMonth() + 1}</div>
        <div class="dc-free">${d.full ? "Full" : d.free_slots + " open"}</div>
      `;
      if (!d.full) {
        chip.addEventListener("click", () => selectDate(doctorId, d, chip));
      } else {
        chip.disabled = true;
      }
      rail.appendChild(chip);
      if (idx === 0 && !d.full) {
        selectDate(doctorId, d, chip);
      }
    });
  } catch (e) {
    rail.innerHTML = `<div class="empty-note" style="color: var(--coral-dark);">Couldn't load dates: ${escapeHtml(e.message)}</div>`;
  }
}

function selectDate(doctorId, dateMeta, chipEl) {
  state.date = dateMeta.date;
  state.dateMeta = dateMeta;
  state.time = null;
  document.querySelectorAll("#dateRail .date-chip").forEach((c) => c.classList.remove("is-selected"));
  chipEl.classList.add("is-selected");
  hideConflict();
  hideSummary();
  loadSlots(doctorId, dateMeta.date);
}

async function loadSlots(doctorId, dateStr) {
  const grid = document.getElementById("slotGrid");
  grid.innerHTML = `<div class="loading">Loading OPD time slots&hellip;</div>`;
  try {
    const slots = await api(`/doctors/${doctorId}/slots?date=${dateStr}`);
    if (!slots.length) {
      grid.innerHTML = `<div class="empty-note">Doctor is off duty / on leave on this date.</div>`;
      return;
    }
    grid.innerHTML = "";
    slots.forEach((s) => {
      const chip = document.createElement("button");
      chip.type = "button";
      const disabled = s.status !== "AVAILABLE";
      chip.className = "slot-chip" + (s.status === "BOOKED" ? " is-taken" : s.status === "PAST" ? " is-past" : "");
      chip.textContent = formatTime(s.time) + (s.status === "PAST" ? " (passed)" : "");
      if (disabled) {
        chip.disabled = true;
      } else {
        chip.addEventListener("click", () => selectSlot(s.time, chip));
      }
      grid.appendChild(chip);
    });
  } catch (e) {
    grid.innerHTML = `<div class="empty-note" style="color: var(--coral-dark);">Couldn't load slots: ${escapeHtml(e.message)}</div>`;
  }
}

function selectSlot(time, chipEl) {
  state.time = time;
  document.querySelectorAll("#slotGrid .slot-chip").forEach((c) => c.classList.remove("is-selected"));
  if (chipEl) chipEl.classList.add("is-selected");
  hideConflict();
  showSummary();
}

function showSummary() {
  const block = document.getElementById("summaryBlock");
  const card = document.getElementById("summaryCard");
  card.innerHTML = `
    <div><div class="sc-label">Patient</div><div class="sc-value">${escapeHtml(state.patient.name)}</div></div>
    <div><div class="sc-label">Age / Gender</div><div class="sc-value">${escapeHtml(state.patient.age)} yrs / ${escapeHtml(state.patient.gender)}</div></div>
    <div><div class="sc-label">Mobile</div><div class="sc-value">${escapeHtml(state.patient.mobile)}</div></div>
    <div><div class="sc-label">Branch</div><div class="sc-value">${escapeHtml(state.branch.name)}</div></div>
    <div><div class="sc-label">Department</div><div class="sc-value">${escapeHtml(state.department.name)}</div></div>
    <div><div class="sc-label">Doctor</div><div class="sc-value">${escapeHtml(state.doctor.name)}</div></div>
    <div><div class="sc-label">Date &amp; Time</div><div class="sc-value">${formatDate(state.date)} &bull; ${formatTime(state.time)}</div></div>
  `;
  document.getElementById("bookError").hidden = true;
  block.hidden = false;
}

function hideSummary() {
  document.getElementById("summaryBlock").hidden = true;
}

function hideConflict() {
  document.getElementById("conflictBox").hidden = true;
  document.getElementById("conflictOptions").innerHTML = "";
}

function showConflict(alternatives) {
  hideSummary();
  const box = document.getElementById("conflictBox");
  const opts = document.getElementById("conflictOptions");
  opts.innerHTML = "";

  const addBtn = (label, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", onClick);
    opts.appendChild(b);
  };

  // Alternative Doctors in Same Branch and Same Department
  if (alternatives.alternative_doctors && alternatives.alternative_doctors.length > 0) {
    const altHead = document.createElement("div");
    altHead.className = "alt-date-label";
    altHead.style.fontWeight = "700";
    altHead.style.color = "var(--teal-deep)";
    altHead.textContent = `Alternative specialists available in ${state.department.name} at ${state.branch.name}:`;
    opts.appendChild(altHead);

    alternatives.alternative_doctors.forEach((altDoc) => {
      altDoc.available_slots.forEach((slotTime) => {
        addBtn(`Dr. ${altDoc.name} @ ${formatTime(slotTime)}`, () => {
          hideConflict();
          state.doctor = {
            id: altDoc.id,
            name: altDoc.name,
            qualification: altDoc.qualification
          };
          selectDoctor(state.doctor, null);
          selectSlot(slotTime, null);
        });
      });
    });
  }

  if (alternatives.next_available_time) {
    addBtn(`${formatTime(alternatives.next_available_time)} (Later Today with Dr. ${state.doctor.name})`, () => {
      hideConflict();
      const time = alternatives.next_available_time;
      loadSlots(state.doctor.id, state.date).then(() => {
        const chip = [...document.querySelectorAll("#slotGrid .slot-chip")]
          .find((c) => c.textContent === formatTime(time));
        selectSlot(time, chip);
      });
    });
  }

  if (alternatives.next_available_date) {
    const label = document.createElement("div");
    label.className = "alt-date-label";
    label.textContent = `Or next opening with Dr. ${state.doctor.name} on ${formatDate(alternatives.next_available_date)}:`;
    opts.appendChild(label);
    alternatives.next_available_date_slots.forEach((t) => {
      addBtn(formatTime(t), () => {
        hideConflict();
        state.date = alternatives.next_available_date;
        loadSlots(state.doctor.id, state.date).then(() => {
          const chip = [...document.querySelectorAll("#slotGrid .slot-chip")]
            .find((c) => c.textContent === formatTime(t));
          selectSlot(t, chip);
        });
      });
    });
  }

  box.hidden = false;
}

const confirmBookingBtn = document.getElementById("confirmButton");
if (confirmBookingBtn) {
  confirmBookingBtn.addEventListener("click", async () => {
    const btn = document.getElementById("confirmButton");
    const errBox = document.getElementById("bookError");
    errBox.hidden = true;
    btn.disabled = true;
    btn.textContent = "Processing Booking...";

    try {
      const payload = {
        patient_name: state.patient.name,
        age: Number(state.patient.age),
        gender: state.patient.gender,
        mobile: state.patient.mobile,
        email: state.patient.email || null,
        address: state.patient.address,
        reason: state.patient.reason,
        branch_id: state.branch.id,
        department_id: state.department.id,
        doctor_id: state.doctor.id,
        appointment_date: state.date,
        time_slot: state.time,
      };
      const result = await api("/appointments/book", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (result.status === "CONFLICT") {
        showConflict(result.alternatives);
        return;
      }

      state.booking = result;
      renderTicket(result);
      if (cancelBookingBtn) cancelBookingBtn.hidden = false;
      goToStep(6);
    } catch (e) {
      errBox.textContent = e.message;
      errBox.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Confirm Booking";
    }
  });
}

if (cancelBookingBtn) {
  cancelBookingBtn.addEventListener("click", () => {
    window.location.href = "manage.html";
  });
}

// ---------------------------------------------------------------------------
// STEP 6 — Ticket Rendering
// ---------------------------------------------------------------------------

function renderTicket(result) {
  const s = result.summary;
  document.getElementById("ticket").innerHTML = `
    <div class="ticket-row1">
      <div>
        <div class="ticket-code-label">Appointment Reference</div>
        <div class="ticket-code">${escapeHtml(result.appointment_code)}</div>
      </div>
      <div class="ticket-status">CONFIRMED</div>
    </div>
    <div class="ticket-perf"></div>
    <div class="ticket-grid">
      <div><div class="tg-label">Patient</div><div class="tg-value">${escapeHtml(s.patient_name)}</div></div>
      <div><div class="tg-label">Mobile</div><div class="tg-value mono">${escapeHtml(s.mobile)}</div></div>
      <div><div class="tg-label">Doctor</div><div class="tg-value">${escapeHtml(s.doctor)}</div></div>
      <div><div class="tg-label">Department</div><div class="tg-value">${escapeHtml(s.department)}</div></div>
      <div><div class="tg-label">Branch</div><div class="tg-value">${escapeHtml(s.branch)}</div></div>

      <div><div class="tg-label">Date</div><div class="tg-value">${formatDate(s.date)}</div></div>
      <div><div class="tg-label">Time</div><div class="tg-value mono">${formatTime(s.time)}</div></div>
    </div>
  `;
  document.getElementById("notifPreview").innerHTML =
    `<strong>Notification Sent (${escapeHtml(result.notification_sent_to)}):</strong><br>${escapeHtml(result.notification_preview)}`;
}

const bookAnotherBtn = document.getElementById("bookAnother");
if (bookAnotherBtn) {
  bookAnotherBtn.addEventListener("click", () => {
    state.patient = { name: "", mobile: "", email: "", address: "", reason: "" };
    state.branch = null;
    state.department = null;
    state.doctor = null;
    state.date = null;
    state.dateMeta = null;
    state.time = null;
    state.booking = null;

    document.getElementById("patientForm").reset();
    document.getElementById("err-patientName").textContent = "";
    document.getElementById("err-patientMobile").textContent = "";
    const addressError = document.getElementById("err-patientAddress");
    if (addressError) addressError.textContent = "";
    if (cancelBookingBtn) cancelBookingBtn.hidden = true;

    hideConflict();
    hideSummary();
    goToStep(1);
  });
}

// Helpers
function formatTime(t) {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

function formatDate(d) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function hasBookingWizardUI() {
  return Boolean(document.getElementById("stepperFill") && document.getElementById("patientForm"));
}

document.addEventListener("DOMContentLoaded", async () => {
  const bookButton = document.getElementById("bookAppointmentBtn");
  if (bookButton) {
    bookButton.addEventListener("click", async () => {
      await handleBookAppointmentClick();
    });
  }

  if (!hasBookingWizardUI()) {
    return;
  }

  renderStepper();

  if (await hasPatientAuth()) {
    fillAuthenticatedPatientDetails();
  }

  const backToLandingBtn = document.getElementById("backToLandingBtn");
  if (backToLandingBtn) {
    backToLandingBtn.addEventListener("click", showLandingPage);
  }

  const shouldOpenBooking = window.location.hash === "#booking" || new URLSearchParams(window.location.search).get("next")?.includes("#booking");
  if (shouldOpenBooking && (await hasPatientAuth())) {
    fillAuthenticatedPatientDetails().finally(showBookingPage);
  }

  if (window.location.hash === "#booking" && !(await hasPatientAuth())) {
    window.location.href = `patient.html?next=${encodeURIComponent(`${window.location.pathname}#booking`)}`;
  }
});

if (hasBookingWizardUI()) {
  renderStepper();
}
/* ==========================================================================
   Varuvi — WhatsApp button + AI Webchat widget
   Reuses the same booking flow engine as the WhatsApp bot backend
   (POST /api/chat/webchat), so a visitor gets an identical guided booking
   experience whether they use WhatsApp or the chat bubble here.
   ========================================================================== */

// TODO: replace with your real WhatsApp Business number
// Format: country code + number, digits only, no +, no spaces, no dashes.
const WHATSAPP_NUMBER = "919999999999";
const WHATSAPP_DEFAULT_TEXT = "Hello, I'm visiting your website to book an appointment.";

const whatsappFab = document.getElementById("whatsappFab");
if (whatsappFab) {
  whatsappFab.addEventListener("click", () => {
    // wa.me only ever PRE-FILLS the message box — WhatsApp itself never
    // auto-sends it. On desktop this opens WhatsApp Web (or shows the app
    // switcher if not linked); on mobile/tablet it opens the WhatsApp app
    // directly with the text ready in the compose box.
    const url = `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(WHATSAPP_DEFAULT_TEXT)}`;
    window.open(url, "_blank", "noopener");
  });
}

/* ---- AI Webchat ---- */

let chatSessionId = null;
let chatHasOpened = false;

const aiChatFab = document.getElementById("aiChatFab");
const aiChatPanel = document.getElementById("aiChatPanel");
const aiChatClose = document.getElementById("aiChatClose");
const aiChatBody = document.getElementById("aiChatBody");
const aiChatInput = document.getElementById("aiChatInput");
const aiChatSend = document.getElementById("aiChatSend");
const aiChatInputRow = document.getElementById("aiChatInputRow");
const chatFabBadge = document.getElementById("chatFabBadge");

/* ---- Proactive nudge toast ----
   Shows a "book now" prompt ~6s after page load (once per browser
   session), auto-hides itself after ~9s if ignored, and opens the
   chat panel if the visitor taps it. */
const chatToast = document.getElementById("chatToast");
const chatToastClose = document.getElementById("chatToastClose");
const chatToastCta = document.getElementById("chatToastCta");
const chatToastRow = document.querySelector(".chat-toast-row");

const TOAST_SHOW_DELAY_MS = 6000;
const TOAST_AUTO_HIDE_MS = 9000;
const TOAST_SESSION_KEY = "varuvi_chat_toast_shown";

let toastHideTimer = null;

function hideChatToast() {
  if (!chatToast || chatToast.hidden) return;
  chatToast.classList.add("is-leaving");
  window.clearTimeout(toastHideTimer);
  window.setTimeout(() => {
    chatToast.hidden = true;
    chatToast.classList.remove("is-leaving");
  }, 280);
}

function showChatToast() {
  if (!chatToast || chatHasOpened) return;
  try {
    if (sessionStorage.getItem(TOAST_SESSION_KEY)) return;
    sessionStorage.setItem(TOAST_SESSION_KEY, "1");
  } catch (_) { /* storage unavailable — still fine to show once */ }

  chatToast.hidden = false;
  if (chatFabBadge) chatFabBadge.hidden = false;
  toastHideTimer = window.setTimeout(hideChatToast, TOAST_AUTO_HIDE_MS);
}

window.setTimeout(showChatToast, TOAST_SHOW_DELAY_MS);

if (chatToastClose) {
  chatToastClose.addEventListener("click", hideChatToast);
}
function openChatFromToast() {
  hideChatToast();
  openAiChatPanel();
}
if (chatToastRow) chatToastRow.addEventListener("click", openChatFromToast);
if (chatToastCta) chatToastCta.addEventListener("click", openChatFromToast);

function renderChatMarkdown(text) {
  if (!text) return "";
  const raw = String(text);
  // The bot's replies may use WhatsApp-style single markers (*bold*,
  // _italic_, ~strike~) as well as standard Markdown (**bold**, [text](url),
  // lists, etc). Convert the WhatsApp-style markers to real Markdown first —
  // the lookaround guards make sure we don't touch text that's already
  // wrapped in real ** or ~~ pairs.
  const mdSource = raw
    .replace(/(?<!\*)\*(?!\*)(\S(?:[^*\n]*\S)?)\*(?!\*)/g, "**$1**")
    .replace(/(^|[^\w])_(\S(?:[^_\n]*\S)?)_(?!\w)/g, "$1*$2*")
    .replace(/(?<!~)~(?!~)(\S(?:[^~\n]*\S)?)~(?!~)/g, "~~$1~~");

  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    // Markdown libraries didn't load (e.g. offline) — fall back to plain
    // escaped text with line breaks preserved.
    return escapeHtml(raw).replace(/\n/g, "<br>");
  }
  const html = marked.parse(mdSource, { breaks: true });
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target", "rel"] });
}

function ensureChatSession() {
  if (!chatSessionId) {
    chatSessionId = window.crypto && crypto.randomUUID
      ? crypto.randomUUID()
      : `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  return chatSessionId;
}

/* ---- Timestamps & date dividers (WhatsApp/Messenger style) ---- */

let lastDividerKey = null;

function formatMsgTime(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatDateLabel(date) {
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return "Today";
  if (sameDay(date, yesterday)) return "Yesterday";
  return date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

function maybeInsertDateDivider() {
  const now = new Date();
  const key = now.toDateString();
  if (key === lastDividerKey) return;
  lastDividerKey = key;
  const divider = document.createElement("div");
  divider.className = "chat-date-divider";
  const pill = document.createElement("span");
  pill.textContent = formatDateLabel(now);
  divider.appendChild(pill);
  aiChatBody.appendChild(divider);
}

function appendChatBubble(text, sender) {
  maybeInsertDateDivider();

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble chat-bubble-${sender}`;
  if (sender === "bot") {
    const content = document.createElement("div");
    content.className = "chat-bubble-markdown";
    content.innerHTML = renderChatMarkdown(text);
    bubble.appendChild(content);
    // External links open in a new tab and don't leak referrer info.
    content.querySelectorAll("a[href]").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
  } else {
    const textEl = document.createElement("span");
    textEl.className = "chat-bubble-text";
    textEl.textContent = text;
    bubble.appendChild(textEl);
  }

  // Send time (user) / response time (bot) shown inside the bubble,
  // bottom-right — same pattern as WhatsApp and Messenger.
  const meta = document.createElement("div");
  meta.className = "chat-bubble-meta";
  meta.textContent = formatMsgTime(new Date());
  bubble.appendChild(meta);

  aiChatBody.appendChild(bubble);
  aiChatBody.scrollTop = aiChatBody.scrollHeight;
  return bubble;
}

function appendTypingBubble() {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble-bot chat-bubble-typing";
  bubble.innerHTML = `<span class="typing-dots"><span></span><span></span><span></span></span>`;
  aiChatBody.appendChild(bubble);
  aiChatBody.scrollTop = aiChatBody.scrollHeight;
  return bubble;
}

function renderChatOptions(options) {
  const existing = aiChatBody.querySelector(".chat-options");
  if (existing) existing.remove();

  if (!options || !options.length) {
    aiChatInputRow.hidden = false;
    aiChatInput.focus();
    return;
  }

  aiChatInputRow.hidden = true;
  const wrap = document.createElement("div");
  wrap.className = "chat-options";
  options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-option-btn";
    btn.textContent = opt.title;
    if (opt.description) {
      btn.appendChild(document.createElement("br"));
      const small = document.createElement("span");
      small.className = "chat-option-desc";
      small.textContent = opt.description;
      btn.appendChild(small);
    }
    btn.addEventListener("click", () => sendChatTurn({ option_id: opt.id }, opt.title));
    wrap.appendChild(btn);
  });
  aiChatBody.appendChild(wrap);
  aiChatBody.scrollTop = aiChatBody.scrollHeight;
}

async function sendChatTurn(payloadExtra, userLabel) {
  if (userLabel) appendChatBubble(userLabel, "user");
  const typing = appendTypingBubble();

  try {
    const res = await fetch(`${API_BASE}/chat/webchat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: ensureChatSession(), ...payloadExtra }),
    });
    const data = await res.json();
    typing.remove();
    appendChatBubble(data.text, "bot");
    renderChatOptions(data.options);
    if (data.done) {
      const restart = document.createElement("button");
      restart.type = "button";
      restart.className = "chat-restart-btn";
      restart.textContent = "Start new chat";
      restart.addEventListener("click", startNewChat);
      aiChatBody.appendChild(restart);
      aiChatBody.scrollTop = aiChatBody.scrollHeight;
    }
  } catch (err) {
    typing.remove();
    appendChatBubble("Sorry, I couldn't connect right now. Please try again in a moment.", "bot");
  }
}

async function startNewChat() {
  aiChatBody.innerHTML = "";
  lastDividerKey = null;
  aiChatInputRow.hidden = true;
  try {
    const res = await fetch(`${API_BASE}/chat/webchat/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: ensureChatSession() }),
    });
    const data = await res.json();
    appendChatBubble(data.text, "bot");
    renderChatOptions(data.options);
  } catch (err) {
    appendChatBubble("Sorry, I couldn't connect right now. Please try again in a moment.", "bot");
  }
}

function submitChatText() {
  const val = aiChatInput.value.trim();
  if (!val) return;
  aiChatInput.value = "";
  sendChatTurn({ message: val }, val);
}

function openAiChatPanel() {
  if (!aiChatPanel) return;
  chatHasOpened = true;
  hideChatToast();
  if (chatFabBadge) chatFabBadge.hidden = true;
  aiChatPanel.hidden = false;
  aiChatFab.setAttribute("aria-expanded", "true");
  if (!aiChatBody.childElementCount) {
    startNewChat();
  }
}

if (aiChatFab) {
  aiChatFab.addEventListener("click", openAiChatPanel);
}
if (aiChatClose) {
  aiChatClose.addEventListener("click", () => {
    aiChatPanel.hidden = true;
    aiChatFab.setAttribute("aria-expanded", "false");
  });
}
if (aiChatSend) {
  aiChatSend.addEventListener("click", submitChatText);
}
if (aiChatInput) {
  aiChatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitChatText();
  });
}