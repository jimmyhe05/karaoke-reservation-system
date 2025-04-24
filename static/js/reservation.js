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

// Initialize drag and drop functionality
function initDragAndDrop() {
  // Initialize the idle area as a Sortable container
  const idleArea = document.getElementById("idle-area");
  if (idleArea) {
    new Sortable(idleArea, {
      group: "reservations",
      animation: 150,
      ghostClass: "ghost",
      dragClass: "drag-source",
      handle: ".reservation-card", // Use reservation cards as handles
      draggable: ".reservation-card", // Only reservation cards should be draggable
      onEnd: function (evt) {
        handleReservationMove(evt);
        // Restack cards after drag ends
        restackIdleCards();
      },
    });

    // Add click handler for idle area cards to bring them to the top
    idleArea.addEventListener("click", function (e) {
      const card = e.target.closest(".reservation-card");
      if (card) {
        // Remove the card and add it back to the top
        card.remove();
        idleArea.prepend(card);
        // Restack all cards
        restackIdleCards();

        // Prevent the click from triggering the modal
        e.stopPropagation();
      }
    });

    // Initial stacking of cards
    restackIdleCards();
  }

  // Make each room timeline a sortable container
  document.querySelectorAll(".room-timeline").forEach((timeline) => {
    new Sortable(timeline, {
      group: "reservations",
      animation: 150,
      ghostClass: "ghost",
      dragClass: "drag-source",
      filter: ".time-label", // Prevent dragging time labels
      handle: ".reservation-card", // Use reservation cards as handles
      draggable: ".reservation-card", // Only reservation cards should be draggable
      onEnd: function (evt) {
        handleReservationMove(evt);
      },
    });
  });

  // Make each time slot a drop target
  document.querySelectorAll(".time-slot").forEach((timeSlot) => {
    timeSlot.addEventListener("dragover", function (e) {
      e.preventDefault();
      this.classList.add("drag-over");
    });

    timeSlot.addEventListener("dragleave", function () {
      this.classList.remove("drag-over");
    });

    timeSlot.addEventListener("drop", function (e) {
      e.preventDefault();
      this.classList.remove("drag-over");
    });
  });
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
    const timeSlot = reservationCard.closest(".time-slot");

    if (timeSlot) {
      const hour = timeSlot.dataset.hour || timeSlot.dataset.time.split(":")[0];

      // First remove from idle area in the backend
      fetch(`/remove_from_idle/${reservationId}`, {
        method: "POST",
      })
        .then((response) => response.json())
        .then((data) => {
          console.log("Removed from idle area:", data);
          // Then update the reservation with new time and room
          moveReservation(reservationId, roomId, hour);
        })
        .catch((error) => {
          console.error("Error removing from idle area:", error);
          showToast(
            "Error removing from idle area. Please try again.",
            "error"
          );
        });
    }
    return;
  }

  // If moved between time slots in the same or different room
  if (toContainer.classList.contains("room-timeline")) {
    const roomId = toContainer.dataset.roomId;
    const timeSlot = reservationCard.closest(".time-slot");

    if (timeSlot) {
      const hour = timeSlot.dataset.hour || timeSlot.dataset.time.split(":")[0];
      moveReservation(reservationId, roomId, hour);
    }
  }
}

// Function to call the API to move a reservation
function moveReservation(reservationId, roomId, hour) {
  // Check if we have a valid reservation ID
  if (!reservationId || reservationId === "undefined") {
    console.error("Invalid reservation ID");
    return;
  }

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
  const newEndHour = newStartHour + duration;

  // Format times for API
  const startTime = `${newStartHour.toString().padStart(2, "0")}:00`;
  const endTime = `${Math.floor(newEndHour).toString().padStart(2, "0")}:${(
    (newEndHour % 1) *
    60
  )
    .toString()
    .padStart(2, "0")}`;

  // Update the card's data attributes
  card.dataset.hour = newStartHour;
  card.dataset.startTime = startTime;
  card.dataset.endTime = endTime;

  // Update the card's display
  const timeRange = card.querySelector(".time-range");
  if (timeRange) {
    timeRange.textContent = `${startTime} - ${endTime}`;
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
    })
    .catch((error) => {
      console.error("Error fetching reservations:", error);
      showToast("Error fetching reservations. Please try again.", "error");
    });
}

// Function to update the idle area
function updateIdleArea() {
  const idleArea = document.querySelector(".idle-area");
  if (!idleArea) return;

  // Clear the existing idle reservations
  idleArea.innerHTML = "";

  // Get the current date
  const currentDate = document.getElementById("date").value;

  // Fetch all reservations for the selected date
  fetch(`/api/daily_reservations?date=${currentDate}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to fetch reservations: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      // Check if there are idle reservations in the response
      if (data.idle_reservations && data.idle_reservations.length > 0) {
        // For each idle reservation, create a reservation card
        data.idle_reservations.forEach((reservation) => {
          // Convert the reservation data to the format expected by createIdleReservationCard
          const formattedReservation = {
            id: reservation.id,
            name: reservation.contact_name,
            people: reservation.num_people,
            phone: "", // These fields might not be available in the API response
            notes: "",
            room_id: reservation.room_id,
            start_time: reservation.start_time,
            end_time: reservation.end_time,
          };
          createIdleReservationCard(formattedReservation, idleArea);
        });

        // Re-initialize drag and drop
        initDragAndDrop();
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
  // Create the reservation card
  const card = document.createElement("div");
  card.className = "reservation-card";

  // Set all the data attributes to maintain the reservation's identity
  card.dataset.id = reservation.id;
  card.dataset.reservationId = reservation.id; // Add this for compatibility with both data-id and data-reservation-id
  card.dataset.roomId = reservation.room_id;
  card.dataset.phone = reservation.phone || "";
  card.dataset.notes = reservation.notes || "";

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

// Function to calculate price estimate
function calculatePriceEstimate(startTime, endTime) {
  return fetch("/api/price_estimate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      start_time: startTime,
      end_time: endTime,
    }),
  }).then((response) => {
    if (!response.ok) {
      throw new Error("Failed to calculate price estimate");
    }
    return response.json();
  });
}

// Function to delete a reservation
function deleteReservation(reservationId) {
  if (!reservationId) {
    console.error("No reservation ID provided for deletion");
    showToast("Error: No reservation selected for deletion", "error");
    return Promise.reject(new Error("No reservation ID provided"));
  }

  console.log(`Sending DELETE request for reservation ID: ${reservationId}`);

  return fetch(`/delete_reservation/${reservationId}`, {
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
      console.log("Delete successful:", data);
      showToast("Reservation deleted successfully!");
      return data;
    })
    .catch((error) => {
      console.error("Error deleting reservation:", error);
      showToast(
        error.message || "Error deleting reservation. Please try again.",
        "error"
      );
      throw error;
    });
}

// Export functions for use in HTML
window.showToast = showToast;
window.initDragAndDrop = initDragAndDrop;
window.updateRoomTimelines = updateRoomTimelines;
window.updateIdleArea = updateIdleArea;
window.createReservationCard = createReservationCard;
window.createIdleReservationCard = createIdleReservationCard;
window.markOccupiedTimeSlots = markOccupiedTimeSlots;
window.calculatePriceEstimate = calculatePriceEstimate;
window.deleteReservation = deleteReservation;
