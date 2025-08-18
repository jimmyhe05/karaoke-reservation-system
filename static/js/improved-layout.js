// Improved Layout JavaScript (day navigation handled in reservation.js)

document.addEventListener("DOMContentLoaded", function () {
  // Initialize the improved layout
  initImprovedLayout();

  // Initialize language toggle
  initLanguageToggle();

  // Initialize current time indicator
  initCurrentTimeIndicator();

  // Initialize responsive behavior
  initResponsiveBehavior();
});

// Function to initialize the improved layout
function initImprovedLayout() {
  // Adjust room timeline heights to match the number of time slots
  adjustRoomTimelineHeights();

  // Add click handlers for time slots (moved from initDraggableCards)
  initTimeSlotClickHandlers();

  // Apply positioning to any reservation cards using data attributes
  positionReservationCards();
}

// Function to adjust room timeline heights
function adjustRoomTimelineHeights() {
  const roomTimelines = document.querySelectorAll(".room-timeline");
  const timeLabels = document.querySelector(".time-labels");

  if (!roomTimelines.length || !timeLabels) return;

  // Get the number of time slots (30-minute intervals)
  const numIntervals = timeLabels.querySelectorAll(".time-label").length;

  // Calculate the height based on the number of time labels (e.g., 20px per interval)
  const timelineHeight = numIntervals * 20; // Assuming 20px height per 30-min slot

  // Set the height for all room timelines
  roomTimelines.forEach((timeline) => {
    timeline.style.height = `${timelineHeight}px`;
  });

  // Set the height for the time labels container if needed (might not be necessary depending on CSS)
  // timeLabels.style.height = `${timelineHeight}px`;
}

// Position reservation cards based on data-top / data-height attributes (set server-side)
function positionReservationCards() {
  document.querySelectorAll('.room-timeline .reservation-card').forEach(card => {
    const top = card.getAttribute('data-top');
    const height = card.getAttribute('data-height');
    if (top !== null) {
      card.style.top = `${top}px`;
    }
    if (height !== null) {
      card.style.height = `${height}px`;
    }
  });
}

// Function to format time (e.g., 14:00 -> 2:00 PM)
function formatTime(hour, minute) {
  const period = hour < 12 || hour === 24 ? "AM" : "PM";
  let displayHour = hour % 12;
  if (displayHour === 0) displayHour = 12; // Handle midnight and noon

  // Adjust hour for 1 AM display
  if (hour === 25) {
    displayHour = 1;
  }

  return `${displayHour}:${minute.toString().padStart(2, "0")} ${period}`;
}

// Function to initialize time slot click handlers
function initTimeSlotClickHandlers() {
  // Use event delegation on the content area for efficiency
  const contentArea = document.querySelector(".content-area");
  if (!contentArea) return;

  // Remove previous listener if any to prevent duplicates
  contentArea.removeEventListener("click", handleTimeSlotClick);
  contentArea.addEventListener("click", handleTimeSlotClick);
}

function handleTimeSlotClick(event) {
  const slot = event.target.closest('.time-slot');
  if (!slot || slot.classList.contains('occupied') || event.target.closest('.reservation-card')) return;
  const roomId = slot.closest('.room-timeline').dataset.roomId;
  const hour = parseInt(slot.dataset.hour);
  const minute = parseInt(slot.dataset.minute) || 0;
  const selectedDate = window.calendarSelectedDate || document.getElementById('date')?.value || new Date().toISOString().split('T')[0];
  if (!roomId || isNaN(hour)) return;
  showNewReservationModal(hour, minute, roomId, selectedDate);
}

// Function to initialize language toggle
function initLanguageToggle() {
  const languageToggle = document.getElementById("language-toggle");
  if (!languageToggle) return;

  languageToggle.addEventListener("click", function () {
    const isCurrentlyEn = document.body.classList.contains("lang-en");
    document.body.classList.toggle("lang-zh", !isCurrentlyEn);
    document.body.classList.toggle("lang-en", isCurrentlyEn);

    // Update button text
    languageToggle.textContent = isCurrentlyEn ? "English" : "中文";

    // Save the language preference
    const currentLang = document.body.classList.contains("lang-zh")
      ? "zh"
      : "en";
    localStorage.setItem("preferred_language", currentLang);

    // Update Flatpickr locale if applicable
    if (window.startTimePicker && window.endTimePicker) {
      const locale =
        currentLang === "zh" ? flatpickr.l10ns.zh : flatpickr.l10ns.default;
      window.startTimePicker.set("locale", locale);
      window.endTimePicker.set("locale", locale);
    }
  });

  // Set initial language based on saved preference or browser default
  const savedLang = localStorage.getItem("preferred_language");
  const browserLang = navigator.language.startsWith("zh") ? "zh" : "en";
  const initialLang = savedLang || browserLang;

  document.body.classList.remove("lang-en", "lang-zh");
  document.body.classList.add(`lang-${initialLang}`);
  languageToggle.textContent = initialLang === "zh" ? "English" : "中文";

  // Set initial Flatpickr locale
  if (window.flatpickr) {
    const locale =
      initialLang === "zh" ? flatpickr.l10ns.zh : flatpickr.l10ns.default;
    flatpickr.localize(locale);
  }
}

// Function to initialize current time indicator
function initCurrentTimeIndicator() {
  updateCurrentTimeIndicator();

  // Update every minute
  setInterval(updateCurrentTimeIndicator, 60000);
}

// Function to update current time indicator
function updateCurrentTimeIndicator() {
  const now = new Date();
  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();

  // Business hours: 11 AM to 1 AM next day
  const isBusinessHours =
    (currentHour >= 11 && currentHour < 24) ||
    (currentHour >= 0 && currentHour < 1);

  // Remove existing indicators first
  document
    .querySelectorAll(".current-time-indicator")
    .forEach((el) => el.remove());

  if (!isBusinessHours) {
    return; // Don't show indicator outside business hours
  }

  // Calculate position based on 30-minute slots (20px height each)
  // Adjust hour for calculation (0 AM becomes 24, 1 AM becomes 25)
  let calculationHour = currentHour;
  if (calculationHour < 11) {
    // Hours 0-10 (handle 0 and 1 AM)
    calculationHour += 24;
  }

  // Calculate the number of 30-minute intervals past 11:00 AM
  const minutesPast11AM = (calculationHour - 11) * 60 + currentMinute;
  const intervalsPast11AM = minutesPast11AM / 30;

  // Calculate the top position (20px per interval)
  const position = intervalsPast11AM * 20; // 20px height per 30-min slot

  // Add the indicator to each room timeline
  document.querySelectorAll(".room-timeline").forEach((timeline) => {
    const indicator = document.createElement("div");
    indicator.className = "current-time-indicator";
    indicator.style.top = `${position}px`;
    timeline.appendChild(indicator);
  });
}

// Function to initialize responsive behavior
function initResponsiveBehavior() {
  // Handle window resize
  window.addEventListener("resize", function () {
    adjustRoomTimelineHeights();
    // Re-calculate current time indicator position if needed, though top % should adjust
    updateCurrentTimeIndicator();
  });
}

// Function to show toast notification (keep one version, maybe move to a shared utility file later)
function showToast(message, type = "info") {
  // Use the globally defined showToast from reservation.js if available
  if (
    typeof window.showToast === "function" &&
    window.showToast !== showToast
  ) {
    window.showToast(message, type);
    return;
  }

  // Fallback or primary implementation if reservation.js's isn't loaded first
  const toastContainer = document.querySelector(".toast-container");
  if (!toastContainer) {
    console.warn("Toast container not found. Creating one.");
    const container = document.createElement("div");
    container.className = "toast-container position-fixed top-0 end-0 p-3";
    container.style.zIndex = "1055"; // Ensure it's above modals
    document.body.appendChild(container);
    toastContainer = container;
  }

  const toast = document.createElement("div");
  toast.className = `toast align-items-center text-white border-0 ${
    type === "success"
      ? "bg-success"
      : type === "error"
      ? "bg-danger"
      : "bg-primary"
  }`;
  toast.setAttribute("role", "alert");
  toast.setAttribute("aria-live", "assertive");
  toast.setAttribute("aria-atomic", "true");

  let icon = "";
  if (type === "success") {
    icon = '<i class="fas fa-check-circle me-2"></i>'; // Using Font Awesome example
  } else if (type === "error") {
    icon = '<i class="fas fa-times-circle me-2"></i>';
  } else if (type === "info") {
    icon = '<i class="fas fa-info-circle me-2"></i>';
  }

  toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${icon}${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

  toastContainer.appendChild(toast);

  const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
  bsToast.show();

  // Remove the element after hiding
  toast.addEventListener("hidden.bs.toast", function () {
    toast.remove();
  });
}

// Export functions for use in other scripts or HTML (if needed)
window.initImprovedLayout = initImprovedLayout;
// window.showToast = showToast; // Only if this should be the primary showToast
window.formatTime = formatTime; // Export if needed elsewhere
