// Enhanced Calendar Functionality

// Function to initialize the enhanced calendar
function initEnhancedCalendar() {
  const calendarEl = document.getElementById("calendar");
  if (!calendarEl) return;

  // Remove any existing flatpickr-calendar elements
  const existingFlatpickrCalendars = document.querySelectorAll(
    ".flatpickr-calendar.animate.inline"
  );
  existingFlatpickrCalendars.forEach((calendar) => calendar.remove());

  // Store the selected date
  let selectedDate = new Date().toISOString().split("T")[0];
  calendarEl.dataset.selectedDate = selectedDate;

  // Initialize FullCalendar with enhanced options
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "dayGridMonth",
    selectable: true,
    selectConstraint: {
      start: new Date().setHours(0, 0, 0, 0),
      end: "2025-12-31",
    },
    // Add event rendering for availability
    events: function (info, successCallback) {
      // Format dates as YYYY-MM-DD
      const startDate = new Date(info.start).toISOString().split("T")[0];
      const endDate = new Date(info.end).toISOString().split("T")[0];

      // Fetch availability data for the visible date range
      fetch(`/api/calendar_availability?start=${startDate}&end=${endDate}`)
        .then((response) => response.json())
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
      // Add custom styling for past dates
      if (info.date < new Date().setHours(0, 0, 0, 0)) {
        info.el.classList.add("fc-day-past");
      }

      // Highlight the selected date
      if (info.date.toISOString().split("T")[0] === selectedDate) {
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

        // Add tooltip
        tippy(dayCell, {
          content: createTooltipContent(dateStr, props),
          allowHTML: true,
          placement: "top",
          arrow: true,
          theme: "light",
          interactive: true,
        });
      }
    },
    // Handle date selection
    dateClick: function (info) {
      // Don't allow selecting past dates
      if (info.date < new Date().setHours(0, 0, 0, 0)) {
        return;
      }

      // Update selected date
      selectedDate = info.dateStr;
      calendarEl.dataset.selectedDate = selectedDate;

      // Remove selected class from all days
      document.querySelectorAll(".fc-daygrid-day").forEach((el) => {
        el.classList.remove("selected-date");
      });

      // Add selected class to clicked day
      info.dayEl.classList.add("selected-date");

      // Update room timelines
      updateRoomTimelines(selectedDate);

      // Update the date input
      const dateInput = document.getElementById("date");
      if (dateInput) {
        // Format the date for display
        const displayDate = new Date(selectedDate).toLocaleDateString("en-US", {
          weekday: "short",
          month: "long",
          day: "numeric",
          year: "numeric",
        });
        dateInput.value = displayDate;
      }
    },
    // Calendar header
    headerToolbar: {
      left: "prev,next today",
      center: "title",
      right: "dayGridMonth",
    },
    // Only allow dates from today onwards
    validRange: {
      start: new Date(),
    },
    // Date formatting
    titleFormat: { year: "numeric", month: "long" },
    dayHeaderFormat: { weekday: "short" },
  });

  // Render the calendar
  calendar.render();

  // Store calendar reference globally
  window.calendar = calendar;
  window.calendarEl = calendarEl;

  // Return the calendar instance
  return calendar;
}

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
  // Load Tippy.js for tooltips if not already loaded
  if (typeof tippy === "undefined") {
    const tippyScript = document.createElement("script");
    tippyScript.src =
      "https://cdn.jsdelivr.net/npm/tippy.js@6/dist/tippy-bundle.umd.min.js";
    tippyScript.onload = initEnhancedCalendar;
    document.head.appendChild(tippyScript);
  } else {
    initEnhancedCalendar();
  }
});

// Export functions for use in other scripts
window.initEnhancedCalendar = initEnhancedCalendar;
