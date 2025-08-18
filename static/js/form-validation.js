// Enhanced form validation for the reservation system

// Function to validate a field and show appropriate feedback
function validateField(field, isValid, message) {
  const formGroup = field.closest(
    ".form-group, .col-md-6, .col-md-4, .col-md-12"
  ); // Find parent container
  const feedbackElement = formGroup
    ? formGroup.querySelector(".invalid-feedback")
    : null;

  if (isValid) {
    field.classList.remove("is-invalid");
    field.classList.add("is-valid");
    if (feedbackElement) {
      feedbackElement.style.display = "none";
    }
  } else {
    field.classList.remove("is-valid");
    field.classList.add("is-invalid");
    if (feedbackElement) {
      feedbackElement.textContent = message;
      feedbackElement.style.display = "block";
    } else {
      // Create feedback if it doesn't exist (less ideal)
      const feedback = document.createElement("div");
      feedback.className = "invalid-feedback d-block"; // Use d-block to ensure visibility
      feedback.textContent = message;
      field.parentNode.appendChild(feedback);
    }
  }
  return isValid;
}

// Function to validate time within business hours (11 AM - 1 AM)
// Uses 24-hour format strings (e.g., "11:00", "25:00")
function validateBusinessHours(startTimeField, endTimeField) {
  const startTimeStr = startTimeField.value; // Should be H:i format from flatpickr
  const endTimeStr = endTimeField.value;

  if (!startTimeStr || !endTimeStr) {
    // Don't validate if fields are empty, required validation handles that
    return true; // Or false if you want to force selection
  }

  // Basic check for format (simple)
  const timeRegex = /^\d{2}:\d{2}$/;
  if (!timeRegex.test(startTimeStr) || !timeRegex.test(endTimeStr)) {
    validateField(startTimeField, false, "Invalid time format.");
    validateField(endTimeField, false, "Invalid time format.");
    return false;
  }

  const [startHour, startMinute] = startTimeStr.split(":").map(Number);
  const [endHour, endMinute] = endTimeStr.split(":").map(Number);

  // Convert to minutes from start of business day (11:00) for easier comparison
  // Treat 11:00 as minute 0, 1:00 AM (25:00) as minute 14*60 = 840
  let startTotalMinutes = startHour * 60 + startMinute;
  let endTotalMinutes = endHour * 60 + endMinute;

  // Adjust for overnight times (e.g., 00:30 becomes 24:30)
  if (startHour < 11) startTotalMinutes += 24 * 60;
  if (endHour < 11) endTotalMinutes += 24 * 60;

  const businessStartMinutes = 11 * 60;
  const businessEndMinutes = 25 * 60;

  let isStartValid =
    startTotalMinutes >= businessStartMinutes &&
    startTotalMinutes < businessEndMinutes;
  let isEndValid =
    endTotalMinutes > businessStartMinutes &&
    endTotalMinutes <= businessEndMinutes;
  let isEndAfterStart = endTotalMinutes > startTotalMinutes;

  const startValid = validateField(
    startTimeField,
    isStartValid,
    "Start time must be between 11:00 AM and 12:30 AM."
  );

  const endValid = validateField(
    endTimeField,
    isEndValid && isEndAfterStart,
    !isEndAfterStart
      ? "End time must be after start time."
      : "End time must be between 11:30 AM and 1:00 AM."
  );

  return startValid && endValid;
}

// Function to validate the entire reservation form
function validateReservationForm(form) {
  let isValid = true;
  const fieldsToValidate = [
    {
      id: "contact_name",
      required: true,
      message: "Please enter a contact name.",
    },
    {
      id: "contact_phone",
      required: true,
      message: "Please enter a contact phone number.",
      pattern: /^\+?[\d\s\-\(\)]{7,}$/,
    }, // Simple phone pattern
    {
      id: "contact_email",
      required: false,
      message: "Please enter a valid email address.",
      pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
    },
    {
      id: "num_people",
      required: true,
      message: "Number of people must be between 1 and 20.",
      min: 1,
      max: 20,
    },
    { id: "room_id", required: true, message: "Please select a room." },
    {
      id: "start_time",
      required: true,
      message: "Please select a start time.",
    },
    { id: "end_time", required: true, message: "Please select an end time." },
    // date_value is hidden, assume calendar sets it correctly
  ];

  fieldsToValidate.forEach((config) => {
    const field = form.querySelector(`#${config.id}`);
    if (!field) return; // Skip if field doesn't exist

    let fieldValid = true;
    const value = field.value.trim();

    if (config.required && value === "") {
      fieldValid = false;
      validateField(field, false, config.message);
    } else if (config.pattern && value !== "" && !config.pattern.test(value)) {
      fieldValid = false;
      validateField(field, false, config.message);
    } else if (config.min !== undefined || config.max !== undefined) {
      const numValue = parseInt(value);
      if (
        isNaN(numValue) ||
        (config.min !== undefined && numValue < config.min) ||
        (config.max !== undefined && numValue > config.max)
      ) {
        fieldValid = false;
        validateField(field, false, config.message);
      } else {
        validateField(field, true, ""); // Mark as valid if within range
      }
    } else if (value !== "" || config.required) {
      // Mark as valid if not empty (and passed other checks) or not required and empty
      validateField(field, true, "");
    }

    isValid = isValid && fieldValid;
  });

  // Validate business hours separately after individual time fields are checked
  const startTimeField = form.querySelector("#start_time");
  const endTimeField = form.querySelector("#end_time");
  if (
    startTimeField &&
    endTimeField &&
    startTimeField.value &&
    endTimeField.value
  ) {
    const timeValid = validateBusinessHours(startTimeField, endTimeField);
    isValid = isValid && timeValid;
  }

  return isValid;
}

// Function to clear any previous error messages and validation states
function clearFormValidation(form) {
  // Hide general alert
  const alert = form.querySelector("#form-error-alert");
  if (alert) alert.classList.add("d-none");

  // Remove validation classes and hide feedback
  form.querySelectorAll(".is-invalid, .is-valid").forEach((field) => {
    field.classList.remove("is-invalid", "is-valid");
  });
  form.querySelectorAll(".invalid-feedback").forEach((feedback) => {
    feedback.style.display = "none";
  });
}

// Function to handle form submission with enhanced validation
function handleReservationSubmit(event) {
  event.preventDefault();
  event.stopPropagation(); // Prevent default browser validation UI

  const form = event.target;
  const alertElement = form.querySelector("#form-error-alert");

  // Clear previous validation states
  clearFormValidation(form);

  // Validate the form
  if (!validateReservationForm(form)) {
    // Show general error message
    if (alertElement) {
      alertElement.textContent = "Please correct the errors highlighted below.";
      alertElement.classList.remove("d-none");
    }
    // Optionally show a toast
    // window.showToast("Please correct the errors in the form.", "error");
    return;
  }

  // If validation passes, prepare the data for submission
  const formData = new FormData(form);
  const jsonData = {};
  formData.forEach((value, key) => {
    // Use the hidden date_value for the date
    if (key === "date_display") return;
    if (key === "date_value") key = "date";
    jsonData[key] = value;
  });

  // Determine API endpoint (create or update)
  const reservationId = jsonData["reservation_id"];
  const apiUrl = reservationId
    ? `/update_reservation/${reservationId}`
    : "/reservation"; // Use /reservation for creation
  const method = "POST"; // Always POST for both create and update in this setup

  // Show loading state
  const submitButton = form.querySelector('button[type="submit"]');
  const originalText = submitButton.innerHTML;
  submitButton.disabled = true;
  submitButton.innerHTML =
    '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Saving...';

  // Submit the form
  fetch(apiUrl, {
    method: method,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json", // Indicate we expect JSON back
    },
    body: JSON.stringify(jsonData),
  })
    .then(async (response) => {
      const responseData = await response.json(); // Try to parse JSON regardless of status
      if (!response.ok) {
        // Throw an error with the message from the server's JSON response
        throw new Error(
          responseData.error || `Request failed with status ${response.status}`
        );
      }
      return responseData; // Return parsed JSON data on success
    })
    .then((data) => {
      // Show success message
      window.showToast(
        data.message || "Reservation saved successfully!",
        "success"
      );

      // Close the modal
      const modalElement = document.getElementById("reservationModal");
      const modal = bootstrap.Modal.getInstance(modalElement);
      if (modal) modal.hide();

      // Refresh the view (timelines and idle area)
      const date = document.getElementById("date_value").value;
      if (typeof window.updateRoomTimelines === "function")
        window.updateRoomTimelines(date);
      if (typeof window.updateIdleArea === "function") window.updateIdleArea();
    })
    .catch((error) => {
      console.error("Error saving reservation:", error);

      // Display error message in the form alert
      if (alertElement) {
        alertElement.textContent =
          error.message || "An unexpected error occurred. Please try again.";
        alertElement.classList.remove("d-none");
      }
      // Optionally show a toast as well
      window.showToast(error.message || "Failed to save reservation.", "error");

      // Specific field highlighting based on error message (optional)
      if (
        error.message &&
        error.message.includes("time slot is already occupied")
      ) {
        validateField(
          form.querySelector("#start_time"),
          false,
          "Time conflict."
        );
        validateField(form.querySelector("#end_time"), false, "Time conflict.");
        validateField(
          form.querySelector("#room_id"),
          false,
          "Room unavailable at this time."
        );
      }
      if (error.message && error.message.includes("business hours")) {
        validateField(
          form.querySelector("#start_time"),
          false,
          "Outside business hours."
        );
        validateField(
          form.querySelector("#end_time"),
          false,
          "Outside business hours."
        );
      }
    })
    .finally(() => {
      // Reset button state
      submitButton.disabled = false;
      submitButton.innerHTML = originalText;
    });
}

// Initialize form validation when the DOM is loaded
document.addEventListener("DOMContentLoaded", function () {
  // Add validation to the reservation form
  const reservationForm = document.getElementById("reservationForm");
  if (reservationForm) {
    // Add input/change event listeners for real-time validation feedback (optional)
    reservationForm
      .querySelectorAll("input, select, textarea")
      .forEach((field) => {
        field.addEventListener("input", () => {
          // Re-validate specific fields or the whole form on input
          // Example: Validate times immediately
          if (field.id === "start_time" || field.id === "end_time") {
            const startField = reservationForm.querySelector("#start_time");
            const endField = reservationForm.querySelector("#end_time");
            if (startField.value && endField.value) {
              validateBusinessHours(startField, endField);
            }
          } else {
            // Basic required check for others
            if (field.hasAttribute("required")) {
              validateField(
                field,
                field.value.trim() !== "",
                field.closest(".form-group")?.querySelector("label")
                  ?.textContent + " is required."
              );
            }
            // Add other specific real-time checks if desired
          }
        });
      });

    // Attach the submit handler
    reservationForm.addEventListener("submit", handleReservationSubmit);
  }
});

// Export functions if needed by other scripts (though global scope might be sufficient)
// window.validateField = validateField;
// window.validateBusinessHours = validateBusinessHours;
// window.validateReservationForm = validateReservationForm;
