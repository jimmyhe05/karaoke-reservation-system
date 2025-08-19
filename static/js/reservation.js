// Toast notification function - make it globally accessible
window.showToast = function (message, type = "success") {
  const toastContainer = document.querySelector(".toast-container");

  // Create toast element
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;

  // Create icon based on type
  let icon = "";
  if (type === "success") {
    icon = "✓";
  } else if (type === "error") {
    icon = "✗";
  } else if (type === "info") {
    icon = "ℹ";
  }

  // Create toast content
  toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${message}</div>
    `;

  // Add toast to container
  toastContainer.appendChild(toast);

  // Force reflow to trigger animation
  toast.offsetHeight;

  // Set opacity to 1 to make it visible
  toast.style.opacity = "1";

  // Remove toast after animation completes
  setTimeout(() => {
    toast.remove();
  }, 4200); // Animation duration (700ms in + 3500ms visible + 700ms out)
};

// Legacy drag-and-drop initialization was replaced by the improved
// implementation in `improved-layout.js`. Expose a safe wrapper that
// delegates to the improved initializer when available.
function initDragAndDrop() {
  console.log(
    "Legacy initDragAndDrop disabled; delegating to improvedInitDragAndDrop if present"
  );
  if (typeof window.improvedInitDragAndDrop === "function") {
    try {
      window.improvedInitDragAndDrop();
    } catch (e) {
      console.warn("improvedInitDragAndDrop() threw:", e);
    }
  }
}

// Function to restack cards in the idle area
function restackIdleCards() {
  const idleArea = document.getElementById("idle-area");
  if (!idleArea) return;

  const cards = idleArea.querySelectorAll(".reservation-card");

  // Reset z-index and margins
  cards.forEach((card, index) => {
    card.style.zIndex = 10 - index;

    if (index === 0) {
      card.style.marginTop = "0";
    } else {
      card.style.marginTop = "-40px";
    }
  });
}

// Handle reservation moves between containers
function handleReservationMove(evt) {
  const reservationCard = evt.item;
  const reservationId = reservationCard.dataset.reservationId;
  const fromContainer = evt.from;
  const toContainer = evt.to;

  console.log("Handling reservation move:", {
    reservationId,
    fromContainerId: fromContainer.id,
    fromContainerClass: fromContainer.className,
    toContainerId: toContainer.id,
    toContainerClass: toContainer.className,
  });

  // Check if we have a valid reservation ID
  if (!reservationId || reservationId === "undefined") {
    console.error("Invalid reservation ID");
    return;
  }

  // If moved to idle area
  if (toContainer.id === "idle-area") {
    console.log(`Reservation ${reservationId} moved to idle area`);

    // Move the card to the top of the idle area
    toContainer.removeChild(reservationCard);
    toContainer.prepend(reservationCard);

    // Update the backend to mark this reservation as idle
    fetch(`/move_to_idle/${reservationId}`, {
      method: "POST",
    })
      .then((response) => response.json())
      .then((data) => {
        console.log("Moved to idle area:", data);
        showToast("Reservation moved to idle area");

        // Restack the cards
        restackIdleCards();
      })
      .catch((error) => {
        console.error("Error moving to idle area:", error);
        showToast("Error moving to idle area. Please try again.", "error");
      });

    return;
  }

  // If moved from idle area to a room timeline
  if (
    fromContainer.id === "idle-area" &&
    toContainer.classList.contains("room-timeline")
  ) {
    const roomId = toContainer.dataset.roomId;

    // Find the closest time slot
    let timeSlot = reservationCard.closest(".time-slot");

    // If no time slot is found directly, find the nearest one based on position
    if (!timeSlot) {
      const cardRect = reservationCard.getBoundingClientRect();
      const cardTop = cardRect.top;

      // Find the time slot whose top position is closest to the card's top
      const timeSlots = toContainer.querySelectorAll(".time-slot");
      let closestSlot = null;
      let minDistance = Infinity;

      timeSlots.forEach((slot) => {
        const slotRect = slot.getBoundingClientRect();
        const distance = Math.abs(slotRect.top - cardTop);

        if (distance < minDistance) {
          minDistance = distance;
          closestSlot = slot;
        }
      });

      timeSlot = closestSlot;
    }

    if (timeSlot) {
  const hour = timeSlot.dataset.hour || timeSlot.dataset.time.split(":")[0];
  const minute = timeSlot.dataset.minute || (timeSlot.dataset.time ? timeSlot.dataset.time.split(":")[1] : 0);
  console.log(`Moving from idle to room ${roomId} at ${hour}:${minute}`);

      // First remove from idle area in the backend
      fetch(`/remove_from_idle/${reservationId}`, {
        method: "POST",
      })
        .then((response) => response.json())
        .then((data) => {
          console.log("Removed from idle area:", data);
          // Then update the reservation with new time and room
          moveReservation(reservationId, roomId, hour, minute);
        })
        .catch((error) => {
          console.error("Error removing from idle area:", error);
          showToast(
            "Error removing from idle area. Please try again.",
            "error"
          );
        });
    } else {
      console.error("No time slot found for the reservation");
      showToast("Error: Could not determine the time slot", "error");
    }
    return;
  }

  // If moved between time slots in the same or different room
  if (toContainer.classList.contains("room-timeline")) {
    const roomId = toContainer.dataset.roomId;

    // Find the closest time slot
    let timeSlot = reservationCard.closest(".time-slot");

    // If no time slot is found directly, find the nearest one based on position
    if (!timeSlot) {
      const cardRect = reservationCard.getBoundingClientRect();
      const cardTop = cardRect.top;

      // Find the time slot whose top position is closest to the card's top
      const timeSlots = toContainer.querySelectorAll(".time-slot");
      let closestSlot = null;
      let minDistance = Infinity;

      timeSlots.forEach((slot) => {
        const slotRect = slot.getBoundingClientRect();
        const distance = Math.abs(slotRect.top - cardTop);

        if (distance < minDistance) {
          minDistance = distance;
          closestSlot = slot;
        }
      });

      timeSlot = closestSlot;
    }

    if (timeSlot) {
  const hour = timeSlot.dataset.hour || timeSlot.dataset.time.split(":")[0];
  const minute = timeSlot.dataset.minute || (timeSlot.dataset.time ? timeSlot.dataset.time.split(":")[1] : 0);
  console.log(`Moving to room ${roomId} at ${hour}:${minute}`);
  moveReservation(reservationId, roomId, hour, minute);
    } else {
      console.error("No time slot found for the reservation");
      showToast("Error: Could not determine the time slot", "error");
    }
  }
}

// Function to call the API to move a reservation
function moveReservation(reservationId, roomId, hour, minute = 0) {
  // Check if we have a valid reservation ID
  if (!reservationId || reservationId === "undefined") {
    console.error("Invalid reservation ID");
    return;
  }

  console.log(`Moving reservation ${reservationId} to room ${roomId} at ${hour}:${minute}`);

  // Get the current date from the calendar
  const selectedDate =
    window.calendarEl.dataset.selectedDate ||
    document.getElementById("date").value;

  // Find the reservation card
  const card = document.querySelector(
    `.reservation-card[data-reservation-id="${reservationId}"]`
  );
  if (!card) {
    console.error("Reservation card not found");
    return;
  }

  // Get the current duration from the card
  const duration = parseFloat(card.dataset.duration) || 1;

  // Calculate new start and end times
  const newStartHour = parseInt(hour);
  const newStartMinute = parseInt(minute) || 0;
  const totalMinutes = Math.round(duration * 60);
  const newEndTotalMinutes = newStartHour * 60 + newStartMinute + totalMinutes;
  const newEndHour = Math.floor(newEndTotalMinutes / 60);
  const newEndMinute = newEndTotalMinutes % 60;

  // Format times for API
  const startTime = `${newStartHour.toString().padStart(2, "0")}:${newStartMinute
    .toString()
    .padStart(2, "0")}`;
  const endTime = `${newEndHour.toString().padStart(2, "0")}:${newEndMinute
    .toString()
    .padStart(2, "0")}`;

  // Update the card's data attributes
  card.dataset.hour = newStartHour;
  card.dataset.minute = newStartMinute;
  card.dataset.startTime = startTime;
  card.dataset.endTime = endTime;
  card.dataset.roomId = roomId;

  // Update the card's display
  const timeRange = card.querySelector(".time-range");
  if (timeRange) {
    timeRange.textContent = `${startTime} - ${endTime}`;
  }

  // Special handling for idle room (room_id = 0)
  if (roomId === 0 || roomId === "0") {
    console.log("Moving to idle room");
    // Move to idle area
    fetch(`/move_to_idle/${reservationId}`, {
      method: "POST",
    })
      .then((response) => response.json())
      .then((data) => {
        console.log("Moved to idle area:", data);
        showToast("Reservation moved to idle area");
        // Refresh the room timelines to show the updated reservation
        updateRoomTimelines(selectedDate);
        // Also update the idle area
        updateIdleArea();
      })
      .catch((error) => {
        console.error("Error moving to idle area:", error);
        showToast("Error moving to idle area. Please try again.", "error");
        // Refresh to restore the original state
        updateRoomTimelines(selectedDate);
      });
    return;
  }

  // Call the API to update the reservation
  fetch(`/update_reservation/${reservationId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      room_id: roomId,
      start_time: startTime,
      end_time: endTime,
      date: selectedDate,
    }),
  })
    .then((response) => {
      if (!response.ok) {
        return response.json().then((data) => {
          if (data.conflict) {
            throw new Error(
              "This time slot is already occupied by another reservation. Please choose a different time."
            );
          } else {
            throw new Error(data.error || "Failed to update reservation");
          }
        });
      }
      return response.json();
    })
    .then((data) => {
      console.log("Reservation updated successfully:", data);
      // Show success message
      showToast("Reservation updated successfully!");
      // Refresh the room timelines to show the updated reservation
      updateRoomTimelines(selectedDate);
      // Also update the idle area
      updateIdleArea();
    })
    .catch((error) => {
      console.error("Error updating reservation:", error);
      showToast(
        error.message || "Error updating reservation. Please try again.",
        "error"
      );
      // Refresh to restore the original state
      updateRoomTimelines(selectedDate);
    });
}

// Function to update room timelines
function updateRoomTimelines(date) {
  // Get all room containers
  const roomContainers = document.querySelectorAll(".room-container");

  // Fetch all reservations for the selected date
  fetch(`/api/daily_reservations?date=${date}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to fetch reservations: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      // Process each room
      roomContainers.forEach((roomContainer) => {
        const roomId = parseInt(roomContainer.dataset.roomId);
        const roomTimeline = roomContainer.querySelector(".room-timeline");

        // Clear the existing time slots
        roomTimeline.innerHTML = "";

        // Create time slots from 11:00 to 01:00 (next day)
        for (let hour = 11; hour <= 25; hour++) {
          for (let minute = 0; minute < 60; minute += 30) {
            const displayHour = hour % 24;
            const ampm = displayHour >= 12 ? "PM" : "AM";
            const hour12 = displayHour % 12 || 12;
            const timeLabel = `${hour12}:${
              minute === 0 ? "00" : minute
            } ${ampm}`;
            const timeValue = `${displayHour.toString().padStart(2, "0")}:${
              minute === 0 ? "00" : minute
            }`;

            const timeSlot = document.createElement("div");
            timeSlot.className = "time-slot";
            timeSlot.dataset.time = timeValue;
            timeSlot.dataset.hour = hour.toString();
            timeSlot.dataset.minute = minute.toString();

            const timeLabelElement = document.createElement("div");
            timeLabelElement.className = "time-label";
            timeLabelElement.textContent = timeLabel;

            timeSlot.appendChild(timeLabelElement);
            roomTimeline.appendChild(timeSlot);
          }
        }

        // Find the room data in the response
        const roomData = data.rooms.find((r) => r.id === roomId);
        if (roomData && roomData.reservations) {
          // For each reservation, create a reservation card
          roomData.reservations.forEach((reservation) => {
            // Convert the reservation data to the format expected by createReservationCard
            const formattedReservation = {
              id: reservation.id,
              name: reservation.contact_name,
              people: reservation.num_people,
              phone: "", // These fields might not be available in the API response
              notes: "",
              room_id: roomId,
              start_time: reservation.start_time,
              end_time: reservation.end_time,
            };
            createReservationCard(formattedReservation, roomTimeline);
          });
        }
      });

      // Re-initialize drag and drop
      initDragAndDrop();

      // Re-initialize time slot click handlers
      initTimeSlots();

      // Update the current time indicator after creating new time slots
      setTimeout(updateCurrentTimeIndicator, 100);
    })
    .catch((error) => {
      console.error("Error fetching reservations:", error);
      showToast("Error fetching reservations. Please try again.", "error");
    });
}

// Function to initialize time slots
function initTimeSlots() {
  console.log("Initializing time slot click handlers");
  document.querySelectorAll(".room-timeline").forEach((timeline) => {
    // Remove any existing click handlers
    timeline.removeEventListener("click", timeSlotClickHandler);
    // Add new click handler
    timeline.addEventListener("click", timeSlotClickHandler);
  });
}

// Time slot click handler function
function timeSlotClickHandler(e) {
  const timeSlot = e.target.closest(".time-slot");
  if (timeSlot && !timeSlot.classList.contains("occupied")) {
    const hour = parseInt(timeSlot.dataset.hour);
    const roomId = this.dataset.roomId;
    const selectedDate = window.calendarEl.selectedDates[0];
    if (selectedDate) {
      console.log("Time slot clicked:", { hour, roomId, selectedDate });
      showNewReservationModal(hour, roomId, selectedDate);
    }
  }
}

// Function to update the idle area
function updateIdleArea() {
  const idleArea = document.getElementById("idle-area");
  if (!idleArea) {
    console.error("Idle area not found");
    return;
  }

  console.log("Updating idle area");

  // Clear the existing idle reservations
  idleArea.innerHTML = "";

  // Get the current date
  const currentDate =
    document.getElementById("date").value ||
    window.calendarEl.dataset.selectedDate ||
    new Date().toISOString().split("T")[0];

  console.log("Fetching idle reservations for date:", currentDate);

  // Fetch all reservations for the selected date
  fetch(`/api/daily_reservations?date=${currentDate}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to fetch reservations: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      console.log("Received data for idle area:", data);

      // Check if there are idle reservations in the response
      if (data.idle_reservations && data.idle_reservations.length > 0) {
        console.log(`Found ${data.idle_reservations.length} idle reservations`);

        // For each idle reservation, create a reservation card
        data.idle_reservations.forEach((reservation) => {
          console.log("Creating idle card for reservation:", reservation);

          // Convert the reservation data to the format expected by createIdleReservationCard
          const formattedReservation = {
            id: reservation.id,
            name: reservation.contact_name,
            people: reservation.num_people,
            phone: "", // These fields might not be available in the API response
            notes: reservation.notes || "",
            language: reservation.language || "en",
            room_id: reservation.room_id,
            start_time: reservation.start_time,
            end_time: reservation.end_time,
          };
          createIdleReservationCard(formattedReservation, idleArea);
        });

        // Stack the cards
        restackIdleCards();

        // Re-initialize drag and drop
        initDragAndDrop();
      } else {
        console.log("No idle reservations found");
      }
    })
    .catch((error) => {
      console.error("Error fetching idle reservations:", error);
      showToast("Error fetching idle reservations. Please try again.", "error");
    });
}

// Function to create a reservation card
function createReservationCard(reservation, roomTimeline) {
  // Parse the start and end times
  const startTime = reservation.start_time;
  const endTime = reservation.end_time;

  // Find the corresponding time slots
  const startSlot = roomTimeline.querySelector(
    `.time-slot[data-time="${startTime}"]`
  );
  if (!startSlot) return;

  // Calculate the position and height of the reservation card
  const startHour = parseInt(startTime.split(":")[0]);
  const startMinute = parseInt(startTime.split(":")[1]);

  const endHour = parseInt(endTime.split(":")[0]);
  const endMinute = parseInt(endTime.split(":")[1]);

  // Handle overnight reservations (end time is after midnight)
  let endHourAdjusted = endHour;
  if (endHour < startHour) {
    endHourAdjusted = endHour + 24;
  }

  // Calculate the duration in minutes
  const startMinutes = startHour * 60 + startMinute;
  const endMinutes = endHourAdjusted * 60 + endMinute;
  const durationMinutes = endMinutes - startMinutes;

  // Calculate the height of the reservation card (40px per hour, 20px per 30 minutes)
  const height = (durationMinutes / 30) * 20;

  // Calculate the top position (relative to the start slot)
  const top = startSlot.offsetTop;

  // Create the reservation card
  const card = document.createElement("div");
  card.className = "reservation-card";

  // Set all the data attributes to maintain the reservation's identity
  card.dataset.id = reservation.id;
  card.dataset.reservationId = reservation.id; // Add this for compatibility with both data-id and data-reservation-id
  card.dataset.roomId = reservation.room_id;
  card.dataset.phone = reservation.phone || "";
  card.dataset.notes = reservation.notes || "";
  card.dataset.startTime = startTime;
  card.dataset.endTime = endTime;
  card.dataset.hour = startHour;
  card.dataset.duration = (durationMinutes / 60).toFixed(1); // Store duration in hours

  // Format the time for display using formatTime function if available
  const displayStartTime =
    typeof formatTime === "function"
      ? formatTime(startHour, startMinute)
      : startTime;
  const displayEndTime =
    typeof formatTime === "function" ? formatTime(endHour, endMinute) : endTime;

  // Set the card content
  card.innerHTML = `
        <div class="time-indicator">
            <span class="time-range">${displayStartTime} - ${displayEndTime}</span>
        </div>
        <div class="content">
            <div class="name-row">
                <strong>${reservation.name}</strong>
                <span class="people-count">${reservation.people} 人</span>
            </div>
            ${
              reservation.notes
                ? `<div class="notes">${reservation.notes}</div>`
                : ""
            }
        </div>
    `;

  // Set the card position and size
  card.style.top = `${top}px`;
  card.style.height = `${height}px`;

  // Add the card to the room timeline
  roomTimeline.appendChild(card);

  // Mark the occupied time slots
  markOccupiedTimeSlots(roomTimeline, startTime, endTime, reservation.id);
}

// Function to create an idle reservation card
function createIdleReservationCard(reservation, idleArea) {
  console.log("Creating idle reservation card:", reservation);

  // Create the reservation card
  const card = document.createElement("div");
  card.className = "reservation-card";

  // Set all the data attributes to maintain the reservation's identity
  card.dataset.id = reservation.id;
  card.dataset.reservationId = reservation.id; // Add this for compatibility with both data-id and data-reservation-id
  card.dataset.roomId = reservation.room_id;
  card.dataset.phone = reservation.phone || "";
  card.dataset.notes = reservation.notes || "";
  card.dataset.language = reservation.language || "en";

  // Parse the start and end times
  const startTime = reservation.start_time;
  const endTime = reservation.end_time;

  // Store time information in data attributes
  card.dataset.startTime = startTime;
  card.dataset.endTime = endTime;

  // Parse the start and end times
  const startHour = parseInt(startTime.split(":")[0]);
  const startMinute = parseInt(startTime.split(":")[1]);
  const endHour = parseInt(endTime.split(":")[0]);
  const endMinute = parseInt(endTime.split(":")[1]);

  // Handle overnight reservations (end time is after midnight)
  let endHourAdjusted = endHour;
  if (endHour < startHour) {
    endHourAdjusted = endHour + 24;
  }

  // Calculate the duration in minutes
  const startMinutes = startHour * 60 + startMinute;
  const endMinutes = endHourAdjusted * 60 + endMinute;
  const durationMinutes = endMinutes - startMinutes;

  card.dataset.hour = startHour;
  card.dataset.duration = (durationMinutes / 60).toFixed(1); // Store duration in hours

  // Format the time for display
  const startHour12 = startHour % 12 || 12;
  const startAmPm = startHour >= 12 ? "PM" : "AM";
  const endHour12 = endHour % 12 || 12;
  const endAmPm = endHour >= 12 ? "PM" : "AM";

  const displayStartTime = `${startHour12}:${startMinute
    .toString()
    .padStart(2, "0")} ${startAmPm}`;
  const displayEndTime = `${endHour12}:${endMinute
    .toString()
    .padStart(2, "0")} ${endAmPm}`;

  // Get language display
  let languageDisplay = "";
  switch (reservation.language) {
    case "en":
      languageDisplay = "English";
      break;
    case "zh":
      languageDisplay = "中文";
      break;
    case "ja":
      languageDisplay = "日本語";
      break;
    case "ko":
      languageDisplay = "한국어";
      break;
    case "vi":
      languageDisplay = "Tiếng Việt";
      break;
    case "th":
      languageDisplay = "ไทย";
      break;
    default:
      languageDisplay = "";
  }

  // Set the card content
  card.innerHTML = `
        <div class="time-indicator">
            <span class="time-range">${displayStartTime} - ${displayEndTime}</span>
        </div>
        <div class="content">
            <div class="name-row">
                <strong>${reservation.name}</strong>
                <span class="people-count">${reservation.people} 人</span>
            </div>
            ${
              languageDisplay
                ? `<div class="language">${languageDisplay}</div>`
                : ""
            }
            ${
              reservation.notes
                ? `<div class="notes">${reservation.notes}</div>`
                : ""
            }
        </div>
    `;

  // Add the card to the idle area
  idleArea.appendChild(card);
}

// Function to mark occupied time slots
function markOccupiedTimeSlots(
  roomTimeline,
  startTime,
  endTime,
  reservationId
) {
  // Parse the start and end times
  const startHour = parseInt(startTime.split(":")[0]);
  const startMinute = parseInt(startTime.split(":")[1]);

  const endHour = parseInt(endTime.split(":")[0]);
  const endMinute = parseInt(endTime.split(":")[1]);

  // Handle overnight reservations (end time is after midnight)
  let endHourAdjusted = endHour;
  if (endHour < startHour) {
    endHourAdjusted = endHour + 24;
  }

  // Mark all time slots between start and end as occupied
  const timeSlots = roomTimeline.querySelectorAll(".time-slot");
  timeSlots.forEach((slot) => {
    const slotTime = slot.dataset.time;
    const slotHour = parseInt(slotTime.split(":")[0]);
    const slotMinute = parseInt(slotTime.split(":")[1]);

    // Handle overnight slots (after midnight)
    let slotHourAdjusted = slotHour;
    if (slotHour < 11) {
      slotHourAdjusted = slotHour + 24;
    }

    // Convert to minutes for easier comparison
    const slotMinutes = slotHourAdjusted * 60 + slotMinute;
    const startMinutes = startHour * 60 + startMinute;
    const endMinutes = endHourAdjusted * 60 + endMinute;

    // Check if the slot is within the reservation time range
    if (slotMinutes >= startMinutes && slotMinutes < endMinutes) {
      slot.classList.add("occupied");
      slot.dataset.reservationId = reservationId;
    }
  });
}

// Function to handle quick duration buttons
function initQuickDurationButtons() {
  document.querySelectorAll(".duration-btn").forEach((button) => {
    button.onclick = function () {
  const hours = parseFloat(this.dataset.hours || this.textContent);
      if (!window.startTimePicker || !window.endTimePicker) return;

      const startDate = window.startTimePicker.selectedDates[0];
      if (!startDate) return;

      // Calculate new end time
  const endDate = new Date(startDate);
  endDate.setMinutes(startDate.getMinutes() + hours * 60);

      // Update end time picker
      window.endTimePicker.setDate(endDate);

      // Update price estimate
      updatePriceEstimate();

      // Update button states
  document.querySelectorAll(".duration-btn").forEach((btn) => btn.classList.remove("active"));
      this.classList.add("active");
    };
  });
}

// Function to calculate price estimate
function updatePriceEstimate() {
  const startTimeInput = document.getElementById("start_time");
  const endTimeInput = document.getElementById("end_time");

  if (!startTimeInput || !endTimeInput) {
    console.error("Time inputs not found");
    return;
  }

  // Use the underlying flatpickr selectedDates (reliable 24h values) if available
  if (!window.startTimePicker || !window.endTimePicker) return;
  const sDate = window.startTimePicker.selectedDates[0];
  const eDate = window.endTimePicker.selectedDates[0];
  if (!sDate || !eDate) return;

  let startHour = sDate.getHours();
  const startMinutes = sDate.getMinutes();
  let endHour = eDate.getHours();
  const endMinutes = eDate.getMinutes();

  // Handle overnight case
  if (endHour < startHour) endHour += 24;

  // Calculate total duration in hours (including partial hours)
  const startTimeInMinutes = startHour * 60 + startMinutes;
  const endTimeInMinutes = endHour * 60 + endMinutes;
  const durationInMinutes = endTimeInMinutes - startTimeInMinutes;
  const durationInHours = durationInMinutes / 60;

  // Initialize variables for period tracking
  let earlyBirdHours = 0;
  let eveningHours = 0;

  // Process each 30-minute interval
  for (let time = startTimeInMinutes; time < endTimeInMinutes; time += 30) {
    let currentHour = Math.floor(time / 60);
    if (currentHour >= 24) currentHour -= 24;

    if (currentHour >= 11 && currentHour < 18) {
      // Early Bird Special (11am-6pm)
      earlyBirdHours += 0.5;
    } else if (currentHour >= 18 || currentHour < 1) {
      // Evening Rate (6pm-1am)
      eveningHours += 0.5;
    }
  }

  // Calculate charges for each period
  const earlyBirdCharge = earlyBirdHours * 35;
  const eveningCharge = eveningHours * 50;
  const totalCharge = earlyBirdCharge + eveningCharge;

  // Create period charges array
  const periodCharges = [];
  if (earlyBirdHours > 0) {
    periodCharges.push({
      label: "Early Bird Rate (11am-6pm)",
      rate: 35,
      duration: earlyBirdHours,
      amount: earlyBirdCharge,
    });
  }

  if (eveningHours > 0) {
    periodCharges.push({
      label: "Evening Rate (6pm-1am)",
      rate: 50,
      duration: eveningHours,
      amount: eveningCharge,
    });
  }

  // Calculate tax and total
  const taxRate = 0.055; // 5.5%
  const taxAmount = totalCharge * taxRate;
  const totalWithTax = totalCharge + taxAmount;

  // Update displays
  try {
    // Update room rate
  const roomRateElement = document.getElementById("room-rate");
    if (roomRateElement) {
      roomRateElement.textContent = `$${totalCharge.toFixed(2)}`;
    }

    // Update tax
    const taxElement = document.getElementById("tax-amount");
    if (taxElement) {
      taxElement.textContent = `$${taxAmount.toFixed(2)}`;
    }

    // Update total
  const totalElement = document.getElementById("total-cost");
    if (totalElement) {
      totalElement.textContent = `$${totalWithTax.toFixed(2)}`;
    }

    // Update period charges
    const periodChargesContainer = document.getElementById("period-charges");
    if (periodChargesContainer && periodCharges.length > 0) {
      const periodChargesHtml = periodCharges
        .map((charge) => {
          return `
          <div class="period-charge">
            <div class="period-charge-row">
              <div class="period-label">${charge.label}</div>
              <div class="period-amount">$${charge.amount.toFixed(2)}</div>
            </div>
            <div class="period-details">
              $${charge.rate}/hr × ${charge.duration} ${
            charge.duration === 1 ? "hour" : "hours"
          }
            </div>
          </div>
        `;
        })
        .join("");
      periodChargesContainer.innerHTML = periodChargesHtml;
    } else {
      periodChargesContainer.innerHTML =
        '<div class="no-charges">No charges calculated</div>';
    }

    // Log the calculation for debugging
    console.log("Price calculation:", {
  startTime: `${startHour}:${startMinutes}`,
  endTime: `${endHour}:${endMinutes}`,
      durationInHours,
      earlyBirdHours,
      eveningHours,
      earlyBirdCharge,
      eveningCharge,
      totalCharge,
      taxAmount,
      totalWithTax,
    });
  } catch (error) {
    console.error("Error updating price display:", error);
    console.error("Error details:", error.stack);
  }
}

// Function to delete a reservation
window.deleteReservation = function () {
  console.log(
    "Delete function called, currentReservationId:",
    currentReservationId,
    "window.currentReservationId:",
    window.currentReservationId
  );

  // Get the reservation ID from the form
  const formReservationId = document.getElementById("reservation_id").value;
  console.log("Form reservation ID in deleteReservation:", formReservationId);

  // Use either the form ID, local variable, or global variable
  const reservationIdToDelete =
    formReservationId || currentReservationId || window.currentReservationId;

  console.log("Attempting to delete reservation ID:", reservationIdToDelete);

  if (!reservationIdToDelete) {
    console.error("No reservation ID found for deletion");
    window.showToast("Error: No reservation selected for deletion", "error");
    return;
  }

  // Use a simple browser confirmation dialog instead of a toast
  if (confirm("Are you sure you want to delete this reservation?")) {
    console.log("Confirm delete button clicked");

    // Get the reservation date from the modal's data attribute
    // This is the date of the reservation being deleted, not necessarily today's date
    const reservationDate =
      document.getElementById("reservationModal").dataset.reservationDate;
    console.log("Reservation date from modal:", reservationDate);

    console.log(
      `Sending DELETE request to /delete_reservation/${reservationIdToDelete}`
    );

    fetch(`/delete_reservation/${reservationIdToDelete}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    })
      .then((response) => {
        console.log("Delete response status:", response.status);
        if (!response.ok) {
          return response.text().then((text) => {
            console.error("Error response text:", text);
            throw new Error(`Failed to delete reservation: ${response.status}`);
          });
        }
        return response.json();
      })
      .then((data) => {
        console.log("Delete response:", data);

        // Store the reservation date before closing the modal
        const dateToKeep =
          reservationDate || document.getElementById("date").value;

        // Set a flag to keep the reservation date when closing the modal
        window.keepReservationDate = true;

        // Close the modal
        closeReservationModal();

        // Refresh the page to ensure all data is updated correctly
        window.location.href = `/?date=${dateToKeep}`;

        // Show success message
        window.showToast("Reservation deleted successfully!");
      })
      .catch((error) => {
        console.error("Error deleting reservation:", error);
        window.showToast(
          "Error deleting reservation. Please try again.",
          "error"
        );
      });
  }
};

// Function to update current time indicator
function updateCurrentTimeIndicator() {
  console.log("Updating current time indicator");

  // Get the current time
  const now = new Date();
  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();

  // Check if we're within business hours (11 AM to 1 AM)
  const isWithinBusinessHours = currentHour >= 11 || currentHour < 1;

  // Remove any existing time indicators
  document.querySelectorAll(".current-time-indicator").forEach((indicator) => {
    indicator.remove();
  });

  // Only show indicator during business hours
  if (!isWithinBusinessHours) {
    console.log("Outside business hours, not showing time indicator");
    return;
  }

  // Get all room timelines
  const roomTimelines = document.querySelectorAll(".room-timeline");
  if (roomTimelines.length === 0) {
    console.error("No room timelines found");
    setTimeout(updateCurrentTimeIndicator, 1000);
    return;
  }

  roomTimelines.forEach((timeline) => {
    // Create the time indicator element
    const timeIndicator = document.createElement("div");
    timeIndicator.className = "current-time-indicator";
    timeIndicator.setAttribute("data-timestamp", now.getTime());

    // Find the corresponding time slot
    let displayHour = currentHour;
    if (currentHour >= 0 && currentHour < 1) {
      displayHour = currentHour + 24;
    }

    // Find the time slot for the current hour
    let timeSlot = timeline.querySelector(
      `.time-slot[data-hour="${displayHour}"]`
    );

    if (!timeSlot) {
      // If we can't find the exact hour, find the closest one
      const timeSlots = timeline.querySelectorAll(".time-slot");
      let closestSlot = null;
      let minDistance = Infinity;

      timeSlots.forEach((slot) => {
        const slotHour = parseInt(slot.dataset.hour);
        const distance = Math.abs(slotHour - displayHour);

        if (distance < minDistance) {
          minDistance = distance;
          closestSlot = slot;
        }
      });

      timeSlot = closestSlot;
    }

    if (!timeSlot) {
      console.error(`No time slot found for hour ${displayHour}`);
      return;
    }

    // Calculate position
    const slotTop = timeSlot.offsetTop;
    const minuteOffset = (currentMinute / 60) * 40; // Each hour is 40px tall
    const topPosition = slotTop + minuteOffset;

    // Set the position
    timeIndicator.style.top = `${topPosition}px`;

    // Add time label
    const timeLabel = document.createElement("span");
    timeLabel.className = "current-time-label";
    const hour12 = currentHour % 12 || 12;
    const ampm = currentHour >= 12 ? "PM" : "AM";
    timeLabel.textContent = `${hour12}:${currentMinute
      .toString()
      .padStart(2, "0")} ${ampm}`;

    timeIndicator.appendChild(timeLabel);
    timeline.appendChild(timeIndicator);
  });
}

// Function to initialize the current time indicator and update it continuously
function initCurrentTimeIndicator() {
  console.log("Initializing current time indicator");

  // Update immediately
  updateCurrentTimeIndicator();

  // Update every 1 seconds for more responsive updates
  setInterval(updateCurrentTimeIndicator, 1000);

  // Also update whenever room timelines are updated
  const originalUpdateRoomTimelines = window.updateRoomTimelines;
  window.updateRoomTimelines = function (date) {
    // Call the original function
    originalUpdateRoomTimelines(date);

    // Wait a short time for the DOM to update, then add the time indicator
    setTimeout(updateCurrentTimeIndicator, 500);
  };

  // Also update when switching between calendar views or dates
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      // Page is now visible, update the time indicator
      updateCurrentTimeIndicator();
    }
  });
}

// Function to show new reservation modal
function showNewReservationModal(hour, minute, roomId, selectedDate) {
  // Clear any existing reservation ID
  window.currentReservationId = null;

  // Reset the form
  document.getElementById("reservationForm").reset();

  // Set the date, room, and start time
  // selectedDate may already be a YYYY-MM-DD string; normalize
  let dateStr = selectedDate;
  if (selectedDate instanceof Date) {
    dateStr = selectedDate.toISOString().split("T")[0];
  }
  document.getElementById("date").value = dateStr;
  document.getElementById("room_id").value = roomId;

  // Format the hour for display (handle after midnight cases)
  let displayHour = parseInt(hour);
  if (displayHour >= 24) {
    displayHour = displayHour - 24;
  }

  // Initialize time pickers with default 2-hour duration including minute precision
  initializeTimePickers(displayHour, 2, minute || 0);

  // Hide the delete button for new reservations
  document.getElementById("delete-reservation-btn").style.display = "none";

  // Show the modal
  const modal = new bootstrap.Modal(
    document.getElementById("reservationModal")
  );
  modal.show();

  // Initialize quick duration buttons
  initQuickDurationButtons();

  // Update price estimate
  updatePriceEstimate();
}

// Refactored function to open modal for editing
function openModalForEditing(reservationId) {
  if (!reservationId || reservationId === "undefined") {
    console.error("Invalid reservation ID for editing");
    return;
  }

  console.log(`Opening modal to edit reservation ${reservationId}`);

  // Set the current reservation ID for the modal
  window.currentReservationId = reservationId;

  // Fetch the reservation details and open the modal
  fetch(`/get_reservation/${reservationId}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to fetch reservation: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      // Populate the modal with the reservation data
      document.getElementById("reservation_id").value = data.id;
      document.getElementById("date").value = data.date;
      // Initialize time pickers with fetched times
      if (typeof initializeTimePickers === "function") {
        initializeTimePickers(null, data.start_time, data.end_time);
      } else {
        // Fallback if picker function not ready (shouldn't happen with DOMContentLoaded)
        document.getElementById("start_time").value = data.start_time; // Use raw 24hr format for now
        document.getElementById("end_time").value = data.end_time;
      }
      document.getElementById("room_id").value = data.room_id;
      document.getElementById("num_people").value = data.num_people;
      document.getElementById("contact_name").value = data.contact_name;
      document.getElementById("contact_phone").value = data.contact_phone;
      document.getElementById("contact_email").value = data.contact_email || "";
      document.getElementById("language").value = data.language || "en";
      // Add notes if the field exists in the modal
      const notesField = document.getElementById("notes");
      if (notesField) notesField.value = data.notes || "";

      // Show the delete button
      document.getElementById("delete-reservation-btn").style.display = "block";

      // Open the modal
      const modalElement = document.getElementById("reservationModal");
      const modal =
        bootstrap.Modal.getInstance(modalElement) ||
        new bootstrap.Modal(modalElement);
      modal.show();
    })
    .catch((error) => {
      console.error("Error fetching reservation:", error);
      showToast("Error fetching reservation details", "error");
    });
}

// Function to initialize time pickers
function initializeTimePickers(
  initialHour,
  durationHours = 2,
  initialMinute = 0,
  startTimeStr = null,
  endTimeStr = null
) {
  const startTimeInput = document.getElementById("start_time");
  const endTimeInput = document.getElementById("end_time");

  if (!startTimeInput || !endTimeInput) {
    console.error("Time picker input elements not found");
    return;
  }

  // Destroy existing instances if they exist
  if (window.startTimePicker) window.startTimePicker.destroy();
  if (window.endTimePicker) window.endTimePicker.destroy();

  // --- Start Time Picker ---
  let defaultStartHour = 11;
  let defaultStartMinute = 0;
  if (startTimeStr) {
    const [h, m] = startTimeStr.split(":").map(Number);
    defaultStartHour = h;
    defaultStartMinute = m;
  } else if (initialHour !== null) {
    defaultStartHour = initialHour;
    defaultStartMinute = initialMinute || 0;
  }

  window.startTimePicker = flatpickr(startTimeInput, {
    enableTime: true,
    noCalendar: true,
    dateFormat: "H:i", // 24-hour format for internal value
    altInput: true,
    altFormat: "h:i K", // 12-hour format for display
    time_24hr: false,
    minuteIncrement: 30,
    minTime: "11:00",
    maxTime: "23:59", // Allow up to 11:59 PM for start
    defaultHour: defaultStartHour,
    defaultMinute: defaultStartMinute,
  onChange: function (selectedDates, dateStr) { updateEndTimeMinimum(dateStr); updatePriceEstimate(); },
  onClose: function(){ updatePriceEstimate(); },
  });

  // --- End Time Picker ---
  let defaultEndHour = defaultStartHour + durationHours;
  let defaultEndMinute = defaultStartMinute;
  if (endTimeStr) {
    const [h, m] = endTimeStr.split(":").map(Number);
    defaultEndHour = h;
    defaultEndMinute = m;
  }

  window.endTimePicker = flatpickr(endTimeInput, {
    enableTime: true,
    noCalendar: true,
    dateFormat: "H:i", // 24-hour format for internal value
    altInput: true,
    altFormat: "h:i K", // 12-hour format for display
    time_24hr: false,
    minuteIncrement: 30,
    minTime: "11:30", // Initial minimum
    maxTime: "01:00", // Allow up to 1:00 AM next day
    defaultHour: defaultEndHour % 24, // Adjust for display if >= 24
    defaultMinute: defaultEndMinute,
  onChange: function () { updatePriceEstimate(); document.querySelectorAll('.duration-btn.active').forEach(btn=>btn.classList.remove('active')); },
  onClose: function(){ updatePriceEstimate(); },
  });

  // Set initial minimum for end time based on initial start time
  if (startTimeStr) {
    updateEndTimeMinimum(startTimeStr);
  } else {
    updateEndTimeMinimum(
      `${defaultStartHour}:${String(defaultStartMinute).padStart(2, "0")}`
    );
  }

  // Initial price estimate
  updatePriceEstimate();
}

// Function to update end time minimum based on start time (24hr format input)
function updateEndTimeMinimum(startTime24hr) {
  if (!window.endTimePicker || !startTime24hr) return;

  const [startHour, startMinute] = startTime24hr.split(":").map(Number);

  // Calculate minimum end time (30 minutes after start)
  let minEndHour = startHour;
  let minEndMinute = startMinute + 30;

  if (minEndMinute >= 60) {
    minEndHour += 1;
    minEndMinute -= 60;
  }

  // Format for flatpickr
  const minEndTimeStr = `${String(minEndHour % 24).padStart(2, "0")}:${String(
    minEndMinute
  ).padStart(2, "0")}`;

  // Set the minimum time for the end time picker
  window.endTimePicker.set("minTime", minEndTimeStr);

  // Also, check if the current end time is still valid
  const currentEndTimeStr = window.endTimePicker.input.value;
  if (currentEndTimeStr) {
    const [currentEndHour, currentEndMinute] = currentEndTimeStr
      .split(":")
      .map(Number);
    let currentEndTotalMinutes = currentEndHour * 60 + currentEndMinute;
    let minEndTotalMinutes = minEndHour * 60 + minEndMinute;

    // Handle overnight for comparison
    if (currentEndHour < startHour) currentEndTotalMinutes += 24 * 60;
    if (minEndHour < startHour) minEndTotalMinutes += 24 * 60;

    if (currentEndTotalMinutes < minEndTotalMinutes) {
      // If current end time is now invalid, set it to the minimum
      window.endTimePicker.setDate(minEndTimeStr, true); // Update and trigger change
    }
  }
}

document.addEventListener("DOMContentLoaded", function () {
  // Initialize drag and drop
  initDragAndDrop();

  // Initialize the current time indicator
  initCurrentTimeIndicator();

  // Initialize the page
  initTimeSlots();
  updateRoomTimelines(new Date().toISOString().split("T")[0]);

  // AJAX form submission to immediately show new reservation
  const resForm = document.getElementById('reservationForm');
  if(resForm){
    resForm.addEventListener('submit', function(evt){
      evt.preventDefault();
      const formData = new FormData(resForm);
      const payload = Object.fromEntries(formData.entries());
      const isUpdate = !!payload.reservation_id;
      fetch(isUpdate ? `/update_reservation/${payload.reservation_id}` : '/reservation', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      }).then(r=>r.json().then(j=>({ok:r.ok,status:r.status,body:j})))
      .then(result=>{
        if(!result.ok){
          showToast(result.body.error || 'Failed to save', 'error');
          return;
        }
        showToast(isUpdate ? 'Reservation updated' : 'Reservation created', 'success');
        const activeDate = window.currentSelectedDate || payload.date;
        updateRoomTimelines(activeDate);
        updateIdleArea && updateIdleArea();
        // close modal
        const modalEl = document.getElementById('reservationModal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if(modal) modal.hide();
      }).catch(err=>{
        console.error('Save error', err);
        showToast('Error saving reservation','error');
      });
    });
  }
});

// Date selection helpers now handled in enhanced-calendar.js

// Export functions for use in HTML
window.showToast = showToast;
window.initDragAndDrop = initDragAndDrop;
window.updateRoomTimelines = updateRoomTimelines;
window.updateIdleArea = updateIdleArea;
window.createReservationCard = createReservationCard;
window.createIdleReservationCard = createIdleReservationCard;
window.markOccupiedTimeSlots = markOccupiedTimeSlots;
window.updatePriceEstimate = updatePriceEstimate;
window.deleteReservation = deleteReservation;
window.updateCurrentTimeIndicator = updateCurrentTimeIndicator;
window.initCurrentTimeIndicator = initCurrentTimeIndicator;
window.showNewReservationModal = showNewReservationModal;

// Add event listener for the delete button
document
  .getElementById("delete-reservation-btn")
  .addEventListener("click", function () {
    console.log("Delete button clicked");

    // Get the reservation ID from the form for logging
    const reservationId = document.getElementById("reservation_id").value;
    console.log("Form reservation ID before deletion:", reservationId);

    // Call the window.deleteReservation function which handles confirmation
    try {
      window.deleteReservation();
    } catch (error) {
      console.error("Error in deleteReservation function:", error);
      alert("Error in delete function: " + error.message);
    }
  });
