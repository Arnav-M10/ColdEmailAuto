const copyText = async (value) => navigator.clipboard.writeText(value);

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    await copyText(target.value || target.textContent || "");
  });
});

const copyCompleteButton = document.getElementById("copyComplete");
if (copyCompleteButton) {
  copyCompleteButton.addEventListener("click", async () => {
    const recipient = document.getElementById("recipientText")?.textContent || "";
    const subject = document.getElementById("subjectText")?.value || "";
    const body = document.getElementById("bodyText")?.value || "";
    await copyText(`To: ${recipient}\nSubject: ${subject}\n\n${body}`);
  });
}
