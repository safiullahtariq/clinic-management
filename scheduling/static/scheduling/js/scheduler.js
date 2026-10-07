document.addEventListener('DOMContentLoaded', async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const tenantSlug = urlParams.get('org') || 'longevity-haus';

  // Steps & Buttons
  const step1 = document.getElementById('booking-step-1');
  const step2 = document.getElementById('booking-step-2');
  const step3 = document.getElementById('booking-step-3');
  const stepIndicator = document.getElementById('step-indicator');

  const resourceSelect = document.getElementById('resource-selector');
  const datePicker = document.getElementById('slot-date-picker');
  const slotsContainer = document.getElementById('slots-output');
  const banner = document.getElementById('scheduler-feedback');

  const btnToStep2 = document.getElementById('btn-to-step-2');
  const btnBackTo1 = document.getElementById('btn-back-to-1');
  const btnToStep3 = document.getElementById('btn-to-step-3');
  const btnBackTo2 = document.getElementById('btn-back-to-2');
  const btnConfirm = document.getElementById('btn-confirm-slot');

  let selectedResourceData = null;
  let activeSlot = null;
  let allResources = [];

  // Default date = Today
  datePicker.value = new Date().toISOString().split('T')[0];

  // Helper: Django CSRF Token
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // 1. Modalities Fetch Karein
  try {
    const resResponse = await fetch(`/v1/public/resources?org=${tenantSlug}`);
    allResources = await resResponse.json();
    resourceSelect.innerHTML = '<option value="">Select Modality...</option>' + 
      allResources.map(r => `<option value="${r.id}">${r.name} (${r.credit_cost} credit - ${r.duration_minutes}m)</option>`).join('');
  } catch (err) {
    console.error("Modalities load error:", err);
  }

  resourceSelect.addEventListener('change', () => {
    selectedResourceData = allResources.find(r => r.id === resourceSelect.value);
    btnToStep2.disabled = !selectedResourceData;
  });

  // Navigation: Step 1 -> Step 2
  btnToStep2.onclick = () => {
    step1.style.display = 'none';
    step2.style.display = 'block';
    stepIndicator.textContent = 'Step 2 of 3';
    refreshSlots();
  };

  // Navigation: Step 2 -> Back to Step 1
  btnBackTo1.onclick = () => {
    step2.style.display = 'none';
    step1.style.display = 'block';
    stepIndicator.textContent = 'Step 1 of 3';
  };

  // 2. Slots Calculate Karein
  async function refreshSlots() {
    if (!selectedResourceData) return;
    const date = datePicker.value;
    activeSlot = null;
    btnToStep3.disabled = true;

    slotsContainer.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Calculating open times...</p>';

    try {
      const response = await fetch(`/v1/resources/${selectedResourceData.id}/slots?date=${date}&org=${tenantSlug}`);
      const slots = await response.json();

      slotsContainer.innerHTML = '';
      if (!slots || !slots.length) {
        slotsContainer.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">No open slots for this day.</p>';
        return;
      }

      slots.forEach(slot => {
        const timeFormatted = new Date(slot.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'slot-item';
        btn.textContent = timeFormatted;
        btn.disabled = !slot.available;

        btn.onclick = () => {
          document.querySelectorAll('.slot-item').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          activeSlot = slot;
          btnToStep3.disabled = false;
        };

        slotsContainer.appendChild(btn);
      });
    } catch (err) {
      slotsContainer.innerHTML = '<p style="color:red; font-size:0.85rem;">Slot calculation failed.</p>';
    }
  }

  datePicker.addEventListener('change', refreshSlots);

  // Navigation: Step 2 -> Step 3 (Review)
  btnToStep3.onclick = () => {
    if (!activeSlot) return;
    document.getElementById('summary-service').textContent = selectedResourceData.name;
    const startTimeFormatted = new Date(activeSlot.start).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    document.getElementById('summary-datetime').textContent = startTimeFormatted;
    document.getElementById('summary-credits').textContent = `${selectedResourceData.credit_cost} Credit(s)`;

    banner.style.display = 'none';
    btnConfirm.disabled = false;

    step2.style.display = 'none';
    step3.style.display = 'block';
    stepIndicator.textContent = 'Step 3 of 3';
  };

  // Navigation: Step 3 -> Back to Step 2
  btnBackTo2.onclick = () => {
    step3.style.display = 'none';
    step2.style.display = 'block';
    stepIndicator.textContent = 'Step 2 of 3';
  };

  // 3. Confirm Reservation (Robust Error Handling)
  btnConfirm.onclick = async () => {
    if (!activeSlot || !selectedResourceData) return;
    btnConfirm.disabled = true;
    banner.style.display = 'none';

    try {
      const csrfToken = getCookie('csrftoken') || '';
      const res = await fetch(`/v1/bookings?org=${tenantSlug}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
          resource_id: selectedResourceData.id,
          start_time: activeSlot.start,
          end_time: activeSlot.end
        })
      });

      let result = {};
      try {
        result = await res.json();
      } catch (e) {
        result = { error: 'Invalid response from server' };
      }

      banner.style.display = 'block';

      if (res.ok) {
        banner.style.backgroundColor = '#153e20';
        banner.style.color = '#7bf199';
        banner.textContent = `Reservation Confirmed! Remaining balance: ${result.remaining_credits} credits.`;
        
        // 2 second baad page reload karein taaki table aur balance refresh ho sake
        setTimeout(() => {
          window.location.reload();
        }, 1800);
      } else {
        const errorMsg = result.error || result.detail || result.message || `Error (HTTP ${res.status})`;
        banner.style.backgroundColor = '#4d1919';
        banner.style.color = '#ff9b9b';
        banner.textContent = `Reservation Error: ${errorMsg}`;
        btnConfirm.disabled = false;
      }
    } catch (err) {
      banner.style.display = 'block';
      banner.style.backgroundColor = '#4d1919';
      banner.style.color = '#ff9b9b';
      banner.textContent = 'Server connection error. Please try again.';
      btnConfirm.disabled = false;
    }
  };
});