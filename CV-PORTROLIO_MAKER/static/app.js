const steps = [...document.querySelectorAll(".step")];
const fields = [...document.querySelectorAll(".field[data-panel]")];

function showStep(stepName) {
  steps.forEach((step) => step.classList.toggle("active", step.dataset.step === stepName));
  fields.forEach((field) => field.classList.toggle("hidden", field.dataset.panel !== stepName));
}

steps.forEach((step) => {
  step.addEventListener("click", () => showStep(step.dataset.step));
});

showStep("basics");
