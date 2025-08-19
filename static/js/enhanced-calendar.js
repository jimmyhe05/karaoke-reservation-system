// Enhanced Calendar Functionality

// Function to initialize the enhanced calendar
function initEnhancedCalendar() {
  const calendarEl = document.getElementById("calendar");
  if (!calendarEl) return;

  // Clean up any leftover Flatpickr artifacts (from earlier implementation)
  if (calendarEl.classList.contains('flatpickr-input')) {
    calendarEl.classList.remove('flatpickr-input');
  }
  if (calendarEl.hasAttribute('readonly')) {
    calendarEl.removeAttribute('readonly');
  }

  // Remove any existing flatpickr-calendar elements
  const existingFlatpickrCalendars = document.querySelectorAll(
    ".flatpickr-calendar.animate.inline"
  );
  existingFlatpickrCalendars.forEach((calendar) => calendar.remove());

  // Store the selected date
  let urlPath = window.location.pathname.replace(/^\//,'');
  let selectedDate = (function(){
    if(/\d{2}-\d{2}-\d{4}/.test(urlPath)){
      const [mm,dd,yyyy] = urlPath.split('-');
      return `${yyyy}-${mm}-${dd}`;
    }
    return new Date().toISOString().split('T')[0];
  })();
  calendarEl.dataset.selectedDate = selectedDate;
  // Initialize label immediately
  updateSelectedDateLabel(selectedDate);

  // Initialize FullCalendar with enhanced options
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "dayGridMonth",
    initialDate: selectedDate,
  headerToolbar: false, // use our external controls
  height: 'auto',
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

        // Use simple title-based tooltip: set data-tooltip and class for CSS pseudo-element
        try{
          const tooltipHtml = createTooltipContent(dateStr, props).replace(/<[^>]+>/g, '\\n');
          dayCell.setAttribute('data-tooltip', tooltipHtml);
          dayCell.classList.add('day-title-tooltip');
          dayCell.title = tooltipHtml.replace(/\\n/g, ' ');
        }catch(e){
          try{ dayCell.title = '' }catch(_){}
        }
      }
    },
    // Handle date selection
    dateClick: function (info) {
      // Don't allow selecting past dates
      if (info.date < new Date().setHours(0, 0, 0, 0)) {
        return;
      }

  applySelectedDate(info.dateStr);
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
  console.info('[Calendar] Rendered with selected date', selectedDate);
  // After render ensure selected date highlighted
  applySelectedDate(selectedDate, true);
  // Ensure all day cells have tooltips bound (useful if tippy was present but some cells missed)
  ensureDayCellTooltips();

  // Delegate clicks on day cells to ensure selection works even if FullCalendar handlers aren't available
  const calRoot = document.getElementById('calendar');
  if (calRoot) {
    calRoot.addEventListener('click', function (e) {
      const dayCell = e.target.closest('.fc-daygrid-day');
      if (!dayCell) return;
      // Ignore disabled or past days
      if (dayCell.classList.contains('fc-day-disabled') || dayCell.classList.contains('fc-day-past')) return;
      const date = dayCell.getAttribute('data-date');
      if (!date) return;
      // Apply selected date (this updates label, URL, and timelines)
      applySelectedDate(date);
    });
  }

  // Store calendar reference globally
  window.calendar = calendar;
  window.calendarEl = calendarEl;

  // Return the calendar instance
  return calendar;
}

function applySelectedDate(dateStr, skipCalendarSet){
  const calendarEl = document.getElementById('calendar');
  if(!calendarEl) return;
  calendarEl.dataset.selectedDate = dateStr;
  window.currentSelectedDate = dateStr;
  // Highlight
  document.querySelectorAll('.fc-daygrid-day').forEach(d=>d.classList.remove('selected-date'));
  const cell = document.querySelector(`.fc-daygrid-day[data-date="${dateStr}"]`);
  if(cell) cell.classList.add('selected-date');
  updateSelectedDateLabel(dateStr);
  updateRoomTimelines(dateStr);
  // Update URL path
  try {
    const d = new Date(dateStr+'T00:00:00');
    if(!isNaN(d.getTime())){
      const mm = String(d.getMonth()+1).padStart(2,'0');
      const dd = String(d.getDate()).padStart(2,'0');
      const yyyy = d.getFullYear();
      const newPath = `/${mm}-${dd}-${yyyy}`;
      if(window.location.pathname !== newPath){
        // If this is initial setup, replaceState; otherwise push a new history entry
        if(skipCalendarSet){
          window.history.replaceState({}, '', newPath);
        } else {
          window.history.pushState({selectedDate: dateStr}, '', newPath);
        }
      }
    }
  } catch(e){ console.warn('URL path update failed', e); }
  if(!skipCalendarSet && window.calendar){
    window.calendar.gotoDate(dateStr);
  }
}

// Ensure day cell tooltips are bound; idempotent via data attribute
function ensureDayCellTooltips(){
  if(typeof document === 'undefined') return;
  const cells = document.querySelectorAll('.fc-daygrid-day');
  cells.forEach(cell=>{
    try{
      if(cell.dataset.tooltipBound) return;
      const bg = cell.querySelector('.fc-daygrid-day-bg');
      if(!bg) return;
      try{
        const date = cell.getAttribute('data-date');
        const reservationCountEl = cell.querySelector('.reservation-count');
        const reservationCount = reservationCountEl ? parseInt(reservationCountEl.textContent||'0') : 0;
        const availabilityIndicator = cell.querySelector('.availability-indicator');
        const availableRooms = availabilityIndicator ? (availabilityIndicator.classList.contains('availability-none')?0:1) : 0;
        const props = {
          reservationCount: reservationCount,
          availableRooms: availableRooms,
          totalRooms: 4,
          occupancyPercentage: Math.round((reservationCount/(4||1))*100)
        };
        const tooltipText = createTooltipContent(date, props).replace(/<[^>]+>/g, '\\n');
        cell.setAttribute('data-tooltip', tooltipText);
        cell.classList.add('day-title-tooltip');
        cell.title = tooltipText.replace(/\\n/g,' ');
        cell.dataset.tooltipBound = '1';
      }catch(e){
        if(!cell.title){ try{ cell.title = cell.textContent.trim().slice(0,200); }catch(_){ } }
      }
    }catch(e){/* ignore per-cell failures */}
  });
}

function updateSelectedDateLabel(dateStr){
  const el = document.getElementById('selected-date-label');
  if(!el) return;
  if(!dateStr) dateStr = new Date().toISOString().split('T')[0];
  const [y,m,d] = dateStr.split('-');
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
  // Initialize calendar; we use simple title-based tooltips (CSS) instead of tippy
  initEnhancedCalendar();

  // Hook day navigation buttons (prev/next day modify selected date)
  function shiftDay(offset){
    const base = new Date(window.currentSelectedDate || new Date().toISOString().split('T')[0]);
    base.setDate(base.getDate()+offset);
    const ymd = base.toISOString().split('T')[0];
    applySelectedDate(ymd);
  }
  // Optional month navigation using existing FullCalendar API (if we decide to add buttons later)
  window.shiftMonth = function(offset){
    if(window.calendar){
      window.calendar.incrementDate({ months: offset });
      // Keep selected date within new month (set to first day if month changed drastically)
      const current = window.calendar.getDate();
      const y=current.getFullYear(), m=String(current.getMonth()+1).padStart(2,'0');
      // preserve day if possible else fallback to 01
      let day = (window.currentSelectedDate||'').split('-')[2] || '01';
      const tentative = new Date(`${y}-${m}-${day}T00:00:00`);
      if(tentative.getMonth()+1 !== current.getMonth()+1){
        day='01';
      }
      applySelectedDate(`${y}-${m}-${day}`);
    }
  }
  const prevBtn = document.getElementById('prev-day-btn');
  const nextBtn = document.getElementById('next-day-btn');
  const todayBtn = document.getElementById('today-btn');
  if(prevBtn) prevBtn.addEventListener('click', ()=>shiftDay(-1));
  if(nextBtn) nextBtn.addEventListener('click', ()=>shiftDay(1));
  if(todayBtn) todayBtn.addEventListener('click', ()=>applySelectedDate(new Date().toISOString().split('T')[0]));

  // Fallback: if something wipes calendar innerHTML later, re-init
  const observer = new MutationObserver(()=>{
    if(!document.querySelector('#calendar .fc-view-harness') && document.getElementById('calendar')){
      console.warn('[Calendar] Lost internal markup, re-rendering');
      if(window.calendar){ window.calendar.destroy(); }
      initEnhancedCalendar();
    }
  });
  const calRoot = document.getElementById('calendar');
  if(calRoot){ observer.observe(calRoot,{childList:true}); }
});

// Handle browser navigation (back/forward)
window.addEventListener('popstate', function(e){
  // Try to read date from path
  const path = window.location.pathname.replace(/^\//,'');
  if(/\d{2}-\d{2}-\d{4}/.test(path)){
    const [mm,dd,yyyy] = path.split('-');
    const iso = `${yyyy}-${mm}-${dd}`;
    applySelectedDate(iso, true);
  }
});

// Export functions for use in other scripts
window.initEnhancedCalendar = initEnhancedCalendar;
