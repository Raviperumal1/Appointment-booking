/* ==========================================================================
   Varuvi — manage booking (self-service cancel / reschedule)
   ========================================================================== */

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "http://localhost:8000" : "";

async function ensureSession() {
  try {
    const res = await fetch(`${API_BASE}/patient/auth/session`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.replace(`patient.html?next=${encodeURIComponent(next)}`);
      return false;
    }

    return true;
  } catch (_) {
    const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.location.replace(`patient.html?next=${encodeURIComponent(next)}`);
    return false;
  }
}

(async () => {
  if (!(await ensureSession())) {
    const pendingRedirect = true;
  }
})();

const state = {
  appt: null, // the looked-up appointment row (includes doctor_name, branch_name, etc.)
  selectedDate: null,
  selectedTime: null,
};

async function api(path, options) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    throw new Error((body && body.detail) || `Request failed (${res.status})`);
  }
  return body;
}

function show(id) {
  ["lookupPanel", "detailPanel", "resultPanel"].forEach((p) => {
    document.getElementById(p).hidden = p !== id;
  });
}

// ---------------------------------------------------------------------------
// Lookup
// ---------------------------------------------------------------------------

document.getElementById("lookupButton").addEventListener("click", async () => {
  const code = document.getElementById("lookupCode").value.trim();
  const mobile = document.getElementById("lookupMobile").value.trim();
  const errBox = document.getElementById("lookupError");
  errBox.hidden = true;

  if (!code || !mobile) {
    errBox.textContent = "Enter both the appointment code and mobile number.";
    errBox.hidden = false;
    return;
  }
  
  const btn = document.getElementById("lookupButton");
  btn.disabled = true;
  btn.textContent = "Requesting OTP\u2026";

  try {
    // Request OTP
    await api(`/patient/auth/request-otp`, {
      method: "POST",
      body: JSON.stringify({ mobile })
    });
    
    // Prompt for OTP
    const otp = prompt(`Enter the OTP sent to ${mobile} (Demo: check backend logs)`);
    if (!otp) {
        throw new Error("OTP is required to manage your appointment.");
    }
    
    // Verify OTP
    btn.textContent = "Verifying\u2026";
    await api(`/patient/auth/verify-otp`, {
      method: "POST",
      body: JSON.stringify({ mobile, otp })
    });
    
    btn.textContent = "Loading\u2026";
    const appt = await api(`/appointments/${encodeURIComponent(code)}/lookup`);
    state.appt = appt;
    renderDetail(appt);
    show("detailPanel");
  } catch (err) {
    errBox.textContent = err.message;
    errBox.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Find my appointment";
  }
});

function renderDetail(appt) {
  const card = document.getElementById("detailCard");
  card.innerHTML = `
    <div><div class="sc-label">Appointment code</div><div class="sc-value">${escapeHtml(appt.appointment_code)}</div></div>
    <div><div class="sc-label">Status</div><div class="sc-value">${escapeHtml(appt.status)}</div></div>
    <div><div class="sc-label">Patient</div><div class="sc-value">${escapeHtml(appt.patient_name)}</div></div>
    <div><div class="sc-label">Doctor</div><div class="sc-value">${escapeHtml(appt.doctor_name)}</div></div>
    <div><div class="sc-label">Branch</div><div class="sc-value">${escapeHtml(appt.branch_name)}</div></div>
    <div><div class="sc-label">Department</div><div class="sc-value">${escapeHtml(appt.department_name)}</div></div>
    <div class="sc-fee">
      <div><div class="sc-label">Date &amp; time</div><div class="sc-value">${formatDate(appt.appointment_date)} &middot; ${formatTime(appt.time_slot)}</div></div>
      <div class="sc-value">&#8377;${appt.fee}</div>
    </div>
  `;
  const actionRow = document.getElementById("actionRow");
  actionRow.style.display = appt.status === "BOOKED" ? "flex" : "none";
  document.getElementById("reschedulePanel").hidden = true;
}

document.getElementById("startOverBtn").addEventListener("click", () => {
  state.appt = null;
  document.getElementById("lookupCode").value = "";
  document.getElementById("lookupMobile").value = "";
  show("lookupPanel");
});

// ---------------------------------------------------------------------------
// Cancel
// ---------------------------------------------------------------------------

document.getElementById("cancelBtn").addEventListener("click", async () => {
  if (!confirm(`Cancel appointment ${state.appt.appointment_code}? This can't be undone.`)) return;
  const btn = document.getElementById("cancelBtn");
  btn.disabled = true;
  btn.textContent = "Cancelling\u2026";
  try {
    const result = await api(`/appointments/${state.appt.appointment_code}/cancel`, {
      method: "POST"
    });
    showResult(
      "Appointment cancelled",
      `${state.appt.appointment_code} has been cancelled. The slot is now open for other patients.`,
      result.notification_preview
    );
  } catch (err) {
    alert(`Couldn't cancel: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Cancel appointment";
  }
});

// ---------------------------------------------------------------------------
// Reschedule
// ---------------------------------------------------------------------------

document.getElementById("showRescheduleBtn").addEventListener("click", () => {
  document.getElementById("reschedulePanel").hidden = false;
  state.selectedDate = null;
  state.selectedTime = null;
  document.getElementById("confirmRescheduleBtn").disabled = true;
  hideConflict();
  loadDates();
});

document.getElementById("cancelRescheduleBtn").addEventListener("click", () => {
  document.getElementById("reschedulePanel").hidden = true;
});

async function loadDates() {
  const rail = document.getElementById("dateRail");
  rail.innerHTML = `<div class="loading">Loading dates&hellip;</div>`;
  document.getElementById("slotGrid").innerHTML = "";
  try {
    const dates = await api(`/doctors/${state.appt.doctor_id}/dates?days=14`);
    if (!dates.length) {
      rail.innerHTML = `<div class="empty-note">No upcoming availability for this doctor.</div>`;
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
        chip.addEventListener("click", () => selectDate(d, chip));
      } else {
        chip.disabled = true;
      }
      rail.appendChild(chip);
      if (idx === 0 && !d.full) selectDate(d, chip);
    });
  } catch (err) {
    rail.innerHTML = `<div class="empty-note">Couldn't load dates: ${escapeHtml(err.message)}</div>`;
  }
}

function selectDate(dateMeta, chipEl) {
  state.selectedDate = dateMeta.date;
  state.selectedTime = null;
  document.getElementById("confirmRescheduleBtn").disabled = true;
  document.querySelectorAll("#dateRail .date-chip").forEach((c) => c.classList.remove("is-selected"));
  chipEl.classList.add("is-selected");
  hideConflict();
  loadSlots(dateMeta.date);
}

async function loadSlots(dateStr) {
  const grid = document.getElementById("slotGrid");
  grid.innerHTML = `<div class="loading">Loading time slots&hellip;</div>`;
  try {
    const slots = await api(`/doctors/${state.appt.doctor_id}/slots?date=${dateStr}`);
    grid.innerHTML = "";
    slots.forEach((s) => {
      const chip = document.createElement("button");
      chip.type = "button";
      // The appointment's own current slot still shows as BOOKED (or even
      // PAST, if it already started) from the backend's point of view — it's
      // still their row — so treat it as pickable regardless of status.
      const isOwnCurrentSlot =
        state.appt.appointment_date === dateStr && state.appt.time_slot === s.time;
      const disabled = s.status !== "AVAILABLE" && !isOwnCurrentSlot;
      chip.className = "slot-chip" + (disabled ? (s.status === "PAST" ? " is-past" : " is-taken") : "");
      const suffix = isOwnCurrentSlot ? " (current)" : s.status === "PAST" ? " (passed)" : "";
      chip.textContent = formatTime(s.time) + suffix;
      if (disabled) {
        chip.disabled = true;
      } else {
        chip.addEventListener("click", () => selectSlot(s.time, chip));
      }
      grid.appendChild(chip);
    });
  } catch (err) {
    grid.innerHTML = `<div class="empty-note">Couldn't load slots: ${escapeHtml(err.message)}</div>`;
  }
}

function selectSlot(time, chipEl) {
  state.selectedTime = time;
  document.querySelectorAll("#slotGrid .slot-chip").forEach((c) => c.classList.remove("is-selected"));
  chipEl.classList.add("is-selected");
  hideConflict();
  document.getElementById("confirmRescheduleBtn").disabled = false;
}

function hideConflict() {
  document.getElementById("conflictBox").hidden = true;
  document.getElementById("conflictOptions").innerHTML = "";
}

function showConflict(alternatives) {
  document.getElementById("confirmRescheduleBtn").disabled = true;
  const box = document.getElementById("conflictBox");
  const opts = document.getElementById("conflictOptions");
  opts.innerHTML = "";

  const addBtn = (label, dateStr, time) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", () => {
      hideConflict();
      state.selectedDate = dateStr;
      loadSlots(dateStr).then(() => {
        const chip = [...document.querySelectorAll("#slotGrid .slot-chip")]
          .find((c) => c.textContent.startsWith(formatTime(time)));
        selectSlot(time, chip);
      });
    });
    opts.appendChild(b);
  };

  if (alternatives.next_available_time) {
    addBtn(`${formatTime(alternatives.next_available_time)} (later that day)`, state.selectedDate, alternatives.next_available_time);
  }
  if (alternatives.previous_available_time) {
    addBtn(`${formatTime(alternatives.previous_available_time)} (earlier that day)`, state.selectedDate, alternatives.previous_available_time);
  }
  if (alternatives.next_available_date) {
    const label = document.createElement("div");
    label.className = "alt-date-label";
    label.textContent = `Or on ${formatDate(alternatives.next_available_date)}:`;
    opts.appendChild(label);
    alternatives.next_available_date_slots.forEach((t) => {
      addBtn(formatTime(t), alternatives.next_available_date, t);
    });
  }
  if (!opts.children.length) {
    opts.innerHTML = `<div class="alt-date-label">No other openings found nearby.</div>`;
  }
  box.hidden = false;
}

document.getElementById("confirmRescheduleBtn").addEventListener("click", async () => {
  const btn = document.getElementById("confirmRescheduleBtn");
  btn.disabled = true;
  btn.textContent = "Rescheduling\u2026";
  try {
    const result = await api(`/appointments/${state.appt.appointment_code}/reschedule`, {
      method: "POST",
      body: JSON.stringify({
        appointment_date: state.selectedDate,
        time_slot: state.selectedTime,
      }),
    });

    if (result.status === "CONFLICT") {
      showConflict(result.alternatives);
      return;
    }

    showResult(
      "Appointment rescheduled",
      `${state.appt.appointment_code} is now on ${formatDate(result.summary.date)} at ${formatTime(result.summary.time)}.`,
      result.notification_preview
    );
  } catch (err) {
    alert(`Couldn't reschedule: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirm new time";
  }
});

// ---------------------------------------------------------------------------
// Result screen
// ---------------------------------------------------------------------------

function showResult(title, subtitle, notifPreview) {
  document.getElementById("resultTitle").textContent = title;
  document.getElementById("resultSub").textContent = subtitle;
  document.getElementById("resultNotif").innerHTML = notifPreview
    ? `<strong>Notification sent:</strong><br>${escapeHtml(notifPreview)}`
    : "";
  show("resultPanel");
}

document.getElementById("resultDoneBtn").addEventListener("click", () => {
  state.appt = null;
  document.getElementById("lookupCode").value = "";
  document.getElementById("lookupMobile").value = "";
  show("lookupPanel");
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

function formatDate(d) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

show("lookupPanel");