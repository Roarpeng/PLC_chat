// Apply the saved appearance before the stylesheet or React is rendered.
try {
  const preference = localStorage.getItem("kronos-theme") ?? "auto";
  if (preference === "rubbing" || (preference === "auto" && matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("rubbing-mode");
  }
  if (localStorage.getItem("kronos-calm") === "1") {
    document.documentElement.classList.add("kronos-calm");
  }
} catch {
  // The app defaults to daylight when the browser blocks access to storage.
}
