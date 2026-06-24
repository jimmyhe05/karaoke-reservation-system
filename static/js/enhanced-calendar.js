// Enhanced Calendar Functionality

// Helper to determine if a date is selectable based on role
function isDateSelectable(dateStr) {
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  
  const isWorker = window.currentRole === "staff" || window.currentRole === "admin";
  if (isWorker) {
    // Workers can select past dates up to 30 days ago
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(today.getDate() - 30);
    const thirtyDaysAgoStr = `${thirtyDaysAgo.getFullYear()}-${String(thirtyDaysAgo.getMonth() + 1).padStart(2, "0")}-${String(thirtyDaysAgo.getDate()).padStart(2, "0")}`;
    return dateStr >= thirtyDaysAgoStr;
  } else {
    // Guests/customers can only select today and future dates
    return dateStr >= todayStr;
  }
}

// Function to initialize the enhanced calendar
function initEnhancedCalendar() {
  const calendarEl = document.getElementById("calendar");
  if (!calendarEl) return;

  // Destroy previous calendar if it exists to prevent duplicate renders and memory leaks
  if (window.calendar) {
    try {
      window.calendar.destroy();
    } catch (e) {
      console.warn("Failed to destroy calendar instance", e);
    }
    window.calendar = null;
  }

  // Clean up any leftover Flatpickr artifacts (from earlier implementation)
  if (calendarEl.classList.contains("flatpickr-input")) {
    calendarEl.classList.remove("flatpickr-input");
  }
  if (calendarEl.hasAttribute("readonly")) {
    calendarEl.removeAttribute("readonly");
  }

  // Remove any existing flatpickr-calendar elements
  const existingFlatpickrCalendars = document.querySelectorAll(
    ".flatpickr-calendar.animate.inline"
  );
  existingFlatpickrCalendars.forEach((calendar) => calendar.remove());

  // Store the selected date
  let urlPath = window.location.pathname.replace(/^\//, "");
  let selectedDate = (function () {
    if (/\d{2}-\d{2}-\d{4}/.test(urlPath)) {
      const [mm, dd, yyyy] = urlPath.split("-");
      return `${yyyy}-${mm}-${dd}`;
    }
    return new Date().toISOString().split("T")[0];
  })();
  calendarEl.dataset.selectedDate = selectedDate;
  // Initialize label immediately
  updateSelectedDateLabel(selectedDate);

  // Initialize FullCalendar with enhanced options
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "dayGridMonth",
    initialDate: selectedDate,
    headerToolbar: false, // use our external controls
    height: "auto",
    selectable: true,
    // Add event rendering for availability
    events: function (info, successCallback) {
      // Format dates as YYYY-MM-DD
      const startDate = new Date(info.start).toISOString().split("T")[0];
      const endDate = new Date(info.end).toISOString().split("T")[0];

      // Fetch availability data for the visible date range
      fetch(`/api/calendar_availability?start=${startDate}&end=${endDate}`)
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Calendar availability failed: ${response.status}`);
          }
          return response.json();
        })
        .then((data) => {
          // Transform the data into events
          const events = data.map((day) => ({
            title: "", // No title, we'll use custom rendering
            start: day.date,
            allDay: true,
            display: "background",
            extendedProps: {
              availableRooms: day.availableRooms,
              totalRooms: day.totalRooms,
              reservationCount: day.reservationCount,
              occupancyPercentage: day.occupancyPercentage,
            },
          }));
          successCallback(events);
        })
        .catch((error) => {
          console.error("Error fetching calendar availability:", error);
          successCallback([]);
        });
    },
    // Enhanced day cell rendering
    dayCellDidMount: function (info) {
      const getLocalTodayStr = () => {
        const today = new Date();
        return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      };
      
      const todayStr = getLocalTodayStr();
      const isPast = info.dateStr < todayStr;
      const selectable = isDateSelectable(info.dateStr);

      if (isPast) {
        info.el.classList.add("fc-day-past");
        if (!selectable) {
          info.el.classList.add("fc-day-disabled");
          info.el.style.opacity = "0.4";
          info.el.style.pointerEvents = "none";
        } else {
          // Selectable past date for staff
          info.el.style.opacity = "0.75";
          info.el.style.cursor = "pointer";
          info.el.style.pointerEvents = "auto";
        }
      }

      // Highlight the selected date
      if (info.dateStr === selectedDate) {
        info.el.classList.add("selected-date");
      }
    },
    // Custom event rendering
    eventDidMount: function (info) {
      const event = info.event;
      const props = event.extendedProps;
      const dateStr = event.start.toISOString().split("T")[0];

      // Create availability indicator
      const availabilityIndicator = document.createElement("div");
      availabilityIndicator.className = "availability-indicator";

      // Determine availability class based on percentage
      if (props.availableRooms === 0) {
        availabilityIndicator.classList.add("availability-none");
      } else if (props.availableRooms < props.totalRooms * 0.3) {
        availabilityIndicator.classList.add("availability-low");
      } else if (props.availableRooms < props.totalRooms * 0.7) {
        availabilityIndicator.classList.add("availability-medium");
      } else {
        availabilityIndicator.classList.add("availability-high");
      }

      // Add the indicator to the day cell
      const dayCell = info.el.closest(".fc-daygrid-day");
      if (dayCell) {
        dayCell
          .querySelector(".fc-daygrid-day-bg")
          .appendChild(availabilityIndicator);

        // Add reservation count badge if there are reservations
        if (props.reservationCount > 0) {
          const countBadge = document.createElement("div");
          countBadge.className = "reservation-count";
          countBadge.textContent = props.reservationCount;
          dayCell.querySelector(".fc-daygrid-day-bg").appendChild(countBadge);
        }

        // No hover tooltip needed — intentionally left blank to avoid showing extra info on hover
      }
    },
    // Handle date selection
    dateClick: function (info) {
      if (!isDateSelectable(info.dateStr)) {
        return;
      }

      applySelectedDate(info.dateStr);
    },
    // Keep the month title without duplicating the external navigation controls.
    headerToolbar: {
      left: "",
      center: "title",
      right: "",
    },
    // Date formatting
    titleFormat: { year: "numeric", month: "long" },
    dayHeaderFormat: { weekday: "short" },
  });

  // Render the calendar
  calendar.render();
  console.info("[Calendar] Rendered with selected date", selectedDate);
  // After render ensure selected date highlighted
  applySelectedDate(selectedDate, true);
  // Remove any hover/title tooltip attributes so native browser tooltips don't appear
  ensureDayCellTooltips();

  // Delegate clicks on day cells to ensure selection works even if FullCalendar handlers aren't available
  const calRoot = document.getElementById("calendar");
  if (calRoot && !calRoot._clickListenerAttached) {
    calRoot.addEventListener("click", function (e) {
      const dayCell = e.target.closest(".fc-daygrid-day");
      if (!dayCell) return;
      const date = dayCell.getAttribute("data-date");
      if (!date) return;
      if (!isDateSelectable(date)) {
        return;
      }
      // Apply selected date (this updates label, URL, and timelines)
      applySelectedDate(date);
    });
    calRoot._clickListenerAttached = true;
  }

  // Store calendar reference globally
  window.calendar = calendar;
  window.calendarEl = calendarEl;

  // Return the calendar instance
  return calendar;
}

function applySelectedDate(dateStr, skipCalendarSet) {
  const calendarEl = document.getElementById("calendar");
  if (!calendarEl) return;
  calendarEl.dataset.selectedDate = dateStr;
  window.currentSelectedDate = dateStr;
  // Highlight
  document
    .querySelectorAll(".fc-daygrid-day")
    .forEach((d) => d.classList.remove("selected-date"));
  const cell = document.querySelector(
    `.fc-daygrid-day[data-date="${dateStr}"]`
  );
  if (cell) cell.classList.add("selected-date");
  updateSelectedDateLabel(dateStr);
  if (typeof window.updateRoomTimelines === "function") {
    window.updateRoomTimelines(dateStr);
  }
  // Update URL path
  try {
    const d = new Date(dateStr + "T00:00:00");
    if (!isNaN(d.getTime())) {
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const yyyy = d.getFullYear();
      const newPath = `/${mm}-${dd}-${yyyy}`;
      if (window.location.pathname !== newPath) {
        // If this is initial setup, replaceState; otherwise push a new history entry
        if (skipCalendarSet) {
          window.history.replaceState({}, "", newPath);
        } else {
          window.history.pushState({ selectedDate: dateStr }, "", newPath);
        }
      }
    }
  } catch (e) {
    console.warn("URL path update failed", e);
  }
  if (!skipCalendarSet && window.calendar) {
    window.calendar.gotoDate(dateStr);
  }
}

// Ensure day cell tooltips are bound; idempotent via data attribute
// Tooltip binding intentionally disabled — user requested no hover information on date blocks
// Remove any hover-related attributes/classes from day cells so no hover info appears
function ensureDayCellTooltips() {
  if (typeof document === "undefined") return;
  const cells = document.querySelectorAll(".fc-daygrid-day");
  cells.forEach((cell) => {
    try {
      // Remove title attribute (native tooltip) and data-tooltip and visual class
      if (cell.hasAttribute("title")) cell.removeAttribute("title");
      if (cell.hasAttribute("data-tooltip"))
        cell.removeAttribute("data-tooltip");
      if (cell.classList.contains("day-title-tooltip"))
        cell.classList.remove("day-title-tooltip");
      // mark as cleaned
      cell.dataset.tooltipBound = "0";
    } catch (e) {
      /* ignore per-cell failures */
    }
  });
}

function updateSelectedDateLabel(dateStr) {
  const el = document.getElementById("selected-date-label");
  if (!el) return;
  if (!dateStr) dateStr = new Date().toISOString().split("T")[0];
  const [y, m, d] = dateStr.split("-");
  el.textContent = `${m}-${d}-${y}`;
}

// Expose
window.applySelectedDate = applySelectedDate;
window.updateSelectedDateLabel = updateSelectedDateLabel;

// Helper function to create tooltip content
function createTooltipContent(dateStr, props) {
  // Format the date
  const date = new Date(dateStr);
  const formattedDate = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  // Create tooltip content
  let content = `
        <div class="calendar-tooltip">
            <strong>${formattedDate}</strong>
    `;

  // Add reservation info
  if (props.reservationCount > 0) {
    content += `<p>${props.reservationCount} reservation${
      props.reservationCount !== 1 ? "s" : ""
    }</p>`;
  } else {
    content += `<p>No reservations</p>`;
  }

  // Add availability info
  content += `<p>${props.availableRooms} of ${props.totalRooms} rooms available</p>`;

  // Add occupancy percentage
  content += `<p>Occupancy: ${props.occupancyPercentage}%</p>`;

  // Close the tooltip div
  content += `</div>`;

  return content;
}

// Initialize the enhanced calendar when the DOM is loaded
document.addEventListener("DOMContentLoaded", function () {
  // Month navigation keeps the selected day when possible so the calendar and
  // room schedule always describe the same date.
  window.shiftMonth = function (offset) {
    if (window.calendar) {
      const selectedDate =
        window.currentSelectedDate ||
        window.calendarEl?.dataset?.selectedDate ||
        new Date().toISOString().split("T")[0];
      const [selectedYear, selectedMonth, selectedDay] = selectedDate
        .split("-")
        .map(Number);

      // Always calculate from day 1. Moving directly from dates such as July 31
      // to June would otherwise overflow back into July.
      const targetMonth = new Date(
        selectedYear,
        selectedMonth - 1 + offset,
        1
      );
      const y = targetMonth.getFullYear();
      const targetMonthIndex = targetMonth.getMonth();
      const m = String(targetMonthIndex + 1).padStart(2, "0");
      const lastDayOfMonth = new Date(y, targetMonthIndex + 1, 0).getDate();
      const day = String(Math.min(selectedDay, lastDayOfMonth)).padStart(2, "0");
      applySelectedDate(`${y}-${m}-${day}`);
    }
  };
  const prevMonthBtn = document.getElementById("prev-month-btn");
  const nextMonthBtn = document.getElementById("next-month-btn");
  const todayBtn = document.getElementById("today-btn");
  if (prevMonthBtn)
    prevMonthBtn.addEventListener("click", () => window.shiftMonth(-1));
  if (nextMonthBtn)
    nextMonthBtn.addEventListener("click", () => window.shiftMonth(1));
  if (todayBtn)
    todayBtn.addEventListener("click", () =>
      applySelectedDate(new Date().toISOString().split("T")[0])
    );

  // Bind controls before calendar setup so a later initialization failure cannot
  // leave visible navigation buttons inert.
  initEnhancedCalendar();

  // Fallback: if something wipes calendar innerHTML later, re-init
  const observer = new MutationObserver(() => {
    if (
      !document.querySelector("#calendar .fc-view-harness") &&
      document.getElementById("calendar")
    ) {
      console.warn("[Calendar] Lost internal markup, re-rendering");
      if (window.calendar) {
        window.calendar.destroy();
      }
      initEnhancedCalendar();
    }
  });
  const calRoot = document.getElementById("calendar");
  if (calRoot) {
    observer.observe(calRoot, { childList: true });
  }
});

// Handle browser navigation (back/forward)
window.addEventListener("popstate", function (e) {
  // Try to read date from path
  const path = window.location.pathname.replace(/^\//, "");
  if (/\d{2}-\d{2}-\d{4}/.test(path)) {
    const [mm, dd, yyyy] = path.split("-");
    const iso = `${yyyy}-${mm}-${dd}`;
    applySelectedDate(iso, true);
  }
});

// Export functions for use in other scripts
window.initEnhancedCalendar = initEnhancedCalendar;
