(function () {
  const list = document.getElementById("task-list");
  const addBtn = document.getElementById("add-task");
  if (!list || !addBtn) return;

  addBtn.addEventListener("click", function () {
    const row = document.createElement("div");
    row.className = "task-row";
    row.innerHTML =
      '<input type="text" name="task_name" placeholder="Task name" required>' +
      '<input type="number" name="task_hours" value="3" min="0.25" step="0.25" required>' +
      '<button type="button" class="btn secondary" data-remove-task>Remove</button>';
    list.appendChild(row);
  });

  list.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-remove-task]");
    if (!btn) return;
    const rows = list.querySelectorAll(".task-row");
    if (rows.length <= 1) return;
    btn.closest(".task-row").remove();
  });
})();
