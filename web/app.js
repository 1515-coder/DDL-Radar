const state = { data: { courses: [], deadlines: [], announcements: [], course_content: [] }, filter: "pending", selectedCourses: new Set(), selectionAccount: null, view: "list", calendarDate: new Date(), materialItems: [] };
const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

async function apiRequest(path, options = {}) {
  if (window.pywebview?.api) {
    const result = await window.pywebview.api.request(options.method || "GET", path, options.body ? JSON.parse(options.body) : {});
    return { ok: result.ok, status: result.status, json: async () => result.payload };
  }
  return fetch(path, options);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function relativeDue(value) {
  const diff = new Date(value) - new Date();
  const hours = Math.ceil(diff / 36e5);
  if (hours < 0) return `已逾期 ${Math.ceil(Math.abs(hours) / 24)} 天`;
  if (hours < 24) return `${hours} 小时后`;
  return `${Math.ceil(hours / 24)} 天后`;
}

function taskType(type) {
  return ({ assignment: "作业", quiz: "测验", exam: "考试" })[type] || "任务";
}

function showFailureNotice(message, title = "本次数据提取失败") {
  const dialog = $("#failureNotice");
  $("#failureTitle").textContent = title;
  $("#failureMessage").textContent = message || "平台没有返回有效数据，请稍后重试。";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else alert(`${title}\n\n${$("#failureMessage").textContent}`);
}

function platformKey(item) {
  return item.source === "yanhe" ? "yanhe" : "mooc";
}

function courseTaskId(course) {
  return String(course.zhiyuan_id || course.course_id);
}

function itemKey(item, id = item.course_id) {
  return `${platformKey(item)}:${String(id)}`;
}

function academicTerm(course) {
  if (course.term) return String(course.term);
  if (!course.start_at) return "未标注学期";
  const started = new Date(course.start_at);
  if (Number.isNaN(started.getTime())) return "未标注学期";
  const year = started.getFullYear();
  const month = started.getMonth() + 1;
  return month >= 8 ? `${year}-${year + 1}-1` : `${year - 1}-${year}-2`;
}

function termKey(platform, term) {
  return `term:${platform}:${term}`;
}

function keysForCourses(courses) {
  return courses.map((course) => itemKey(course, courseTaskId(course)));
}

function resetCourseSelection(renderAfter = true) {
  const active = state.data.courses.filter((course) => course.is_active);
  state.selectedCourses = new Set(keysForCourses(active.length ? active : state.data.courses));
  if (renderAfter) render();
}

function updateCourseGroup(keys, checked) {
  keys.forEach((key) => checked ? state.selectedCourses.add(key) : state.selectedCourses.delete(key));
  render();
}

function applyCheckboxState(checkbox, keys) {
  const selected = keys.filter((key) => state.selectedCourses.has(key)).length;
  checkbox.checked = keys.length > 0 && selected === keys.length;
  checkbox.indeterminate = selected > 0 && selected < keys.length;
}

function filteredTasks() {
  return state.data.deadlines.filter((task) => {
    const due = new Date(task.due_at);
    const overdue = !task.completed && !Number.isNaN(due.getTime()) && due < new Date();
    const statusMatch = state.filter === "all"
      || (state.filter === "pending" && !task.completed)
      || (state.filter === "overdue" && overdue)
      || (state.filter === "completed" && task.completed);
    const courseMatch = state.selectedCourses.has(itemKey(task));
    return statusMatch && courseMatch;
  });
}

function renderCourses() {
  const courses = state.data.courses;
  const active = courses.filter((course) => course.is_active);
  $("#activeCourseCount").textContent = `${state.selectedCourses.size}/${courses.length} 已选`;
  $("#courseCount").textContent = active.length;
  const counts = new Map();
  state.data.deadlines.filter((task) => !task.completed).forEach((task) => {
    const key = itemKey(task);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const platforms = [
    { key: "mooc", label: "中国大学 MOOC" },
    { key: "yanhe", label: "延河课堂" },
  ];
  const groups = platforms.map((platform) => {
    const platformCourses = courses.filter((course) => platformKey(course) === platform.key);
    if (!platformCourses.length) return "";
    const terms = new Map();
    platformCourses.forEach((course) => {
      const term = academicTerm(course);
      if (!terms.has(term)) terms.set(term, []);
      terms.get(term).push(course);
    });
    const termGroups = [...terms.entries()].sort(([left], [right]) => right.localeCompare(left, "zh-CN")).map(([term, termCourses]) => {
      const isCurrent = termCourses.some((course) => course.is_active);
      const groupKey = termKey(platform.key, term);
      const items = termCourses.sort((left, right) => String(left.name).localeCompare(String(right.name), "zh-CN")).map((course) => {
        const key = itemKey(course, courseTaskId(course));
        const progress = `${course.learned_lessons || 0}/${course.total_lessons || 0} 学时`;
        return `<label class="course-item course-choice ${state.selectedCourses.has(key) ? "active" : ""}"><input class="course-checkbox" type="checkbox" data-course-key="${escapeHTML(key)}" ${state.selectedCourses.has(key) ? "checked" : ""}><span><strong>${escapeHTML(course.name)}</strong><small>${counts.get(key) || 0} 项待完成 · ${progress}</small></span></label>`;
      }).join("");
      return `<details class="term-group" ${isCurrent ? "open" : ""}><summary><span><input class="term-checkbox" type="checkbox" data-platform="${platform.key}" data-term="${escapeHTML(term)}">${escapeHTML(term)}</span><small>${isCurrent ? "本学期 · " : ""}${termCourses.length} 门</small></summary><div class="term-courses">${items}</div></details>`;
    }).join("");
    return `<details class="platform-group" open><summary class="platform-summary"><span><input class="platform-checkbox" type="checkbox" data-platform="${platform.key}">${platform.label}</span><small>${platformCourses.length} 门</small></summary>${termGroups}</details>`;
  }).join("");
  $("#courseList").innerHTML = `
    <label class="course-item course-choice all-courses"><input id="allCoursesCheckbox" type="checkbox"><span><strong>全部课程</strong><small>${state.data.deadlines.length} 项任务</small></span></label>
    ${groups}`;
  applyCheckboxState($("#allCoursesCheckbox"), keysForCourses(courses));
  document.querySelectorAll(".platform-checkbox").forEach((checkbox) => {
    const groupCourses = courses.filter((course) => platformKey(course) === checkbox.dataset.platform);
    const keys = keysForCourses(groupCourses);
    applyCheckboxState(checkbox, keys);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => updateCourseGroup(keys, checkbox.checked));
  });
  document.querySelectorAll(".term-checkbox").forEach((checkbox) => {
    const groupCourses = courses.filter((course) => platformKey(course) === checkbox.dataset.platform && academicTerm(course) === checkbox.dataset.term);
    const keys = keysForCourses(groupCourses);
    applyCheckboxState(checkbox, keys);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => updateCourseGroup(keys, checkbox.checked));
  });
  $("#allCoursesCheckbox").addEventListener("change", (event) => updateCourseGroup(keysForCourses(courses), event.target.checked));
  document.querySelectorAll(".course-checkbox").forEach((checkbox) => checkbox.addEventListener("change", () => updateCourseGroup([checkbox.dataset.courseKey], checkbox.checked)));
}

function renderTasks() {
  const now = new Date();
  const pending = state.data.deadlines.filter((task) => !task.completed);
  $("#pendingCount").textContent = pending.length;
  $("#weekCount").textContent = pending.filter((task) => new Date(task.due_at) - now <= 7 * 864e5 && new Date(task.due_at) >= now).length;
  const tasks = filteredTasks();
  $("#taskList").innerHTML = tasks.length ? tasks.map((task) => {
    const due = new Date(task.due_at);
    const urgent = !task.completed && due - now < 3 * 864e5;
    return `<a class="task-card ${urgent ? "urgent" : ""} ${task.completed ? "completed" : ""}" href="${task.url}" target="_blank" rel="noreferrer">
      <div class="date-block"><strong>${due.getDate()}</strong><span>${due.getMonth() + 1} 月</span></div>
      <div class="task-main"><h3>${escapeHTML(task.title)}</h3><div class="task-meta"><span>${escapeHTML(task.course)}</span><span class="task-type">${taskType(task.task_type)}</span>${task.score != null ? `<span>${task.score}/${task.total_score} 分</span>` : ""}</div></div>
      <div class="due-state"><strong>${task.completed ? "已完成" : relativeDue(task.due_at)}</strong><span>${formatDate(task.due_at)}</span></div>
    </a>`;
  }).join("") : `<div class="empty"><strong>暂无任务</strong></div>`;
}

function renderCalendar() {
  const year = state.calendarDate.getFullYear();
  const month = state.calendarDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const leadingDays = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const totalCells = Math.ceil((leadingDays + daysInMonth) / 7) * 7;
  const today = new Date();
  const tasks = filteredTasks();
  $("#calendarTitle").textContent = `${year} 年 ${month + 1} 月`;
  $("#calendarGrid").innerHTML = Array.from({ length: totalCells }, (_, index) => {
    const day = index - leadingDays + 1;
    if (day < 1 || day > daysInMonth) return `<div class="calendar-day outside"></div>`;
    const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
    const dayTasks = tasks.filter((task) => {
      const due = new Date(task.due_at);
      return due.getFullYear() === year && due.getMonth() === month && due.getDate() === day;
    });
    return `<div class="calendar-day ${isToday ? "today" : ""}"><span class="day-number">${day}</span>${dayTasks.map((task) => `<a href="${escapeHTML(task.url)}" target="_blank" rel="noreferrer" title="${escapeHTML(task.course)} · ${escapeHTML(task.title)}"><strong>${escapeHTML(task.title)}</strong><span>${new Date(task.due_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}</span></a>`).join("")}</div>`;
  }).join("");
}

function filteredAnnouncements() {
  const announcements = state.data.announcements || [];
  const selectedIds = selectedCourseIds();
  return announcements.filter((item) => !item.course_id || selectedIds.has(String(item.course_id)));
}

function renderAnnouncements() {
  const announcements = filteredAnnouncements();
  $("#announcementList").innerHTML = announcements.length ? announcements.map((item) => {
    const published = item.published_at ? new Date(item.published_at) : null;
    const dateLabel = published && !Number.isNaN(published.getTime())
      ? published.toLocaleString("zh-CN", { hour12: false })
      : "";
    return `<a class="announcement-card" href="${escapeHTML(item.url || "#")}" target="_blank" rel="noreferrer">
      <div class="announcement-meta"><span>${escapeHTML(item.course || "平台公告")}</span>${dateLabel ? `<time>${escapeHTML(dateLabel)}</time>` : ""}</div>
      <h3>${escapeHTML(item.title || "未命名公告")}</h3>
      ${item.content ? `<p>${escapeHTML(item.content)}</p>` : ""}
    </a>`;
  }).join("") : `<div class="empty"><strong>暂无公告</strong><span>刷新数据后会在这里显示课程和平台公告。</span></div>`;
}

function selectedCourseIds() {
  return new Set(state.data.courses
    .filter((course) => state.selectedCourses.has(itemKey(course, courseTaskId(course))))
    .map((course) => String(courseTaskId(course))));
}

function renderCourseContent() {
  const selected = selectedCourseIds();
  const items = (state.data.course_content || []).filter((item) => !selected || selected.has(String(item.course_id)));
  const groups = new Map();
  items.forEach((item) => {
    const key = `${item.course || "未命名课程"}｜${item.category || "其他"}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  $("#courseContentList").innerHTML = items.length ? [...groups.entries()].map(([key, groupItems]) => {
    const [course, category] = key.split("｜");
    return `<section class="content-group"><div class="content-group-heading"><span><strong>${escapeHTML(category)}</strong><small>${escapeHTML(course)}</small></span><b>${groupItems.length} 项</b></div>${groupItems.map((item) => `<a class="content-item" href="${escapeHTML(item.url || "#")}" target="_blank" rel="noreferrer"><span><strong>${escapeHTML(item.title || `${category}项目`)}</strong>${item.content ? `<small>${escapeHTML(item.content)}</small>` : ""}</span><em>${item.activity_type ? escapeHTML(item.activity_type) : "查看"}</em></a>`).join("")}</section>`;
  }).join("") : `<div class="empty"><strong>暂无课程内容</strong><span>刷新后会逐课程检查各个栏目。</span></div>`;
}

function render() {
  renderCourses();
  renderTasks();
  renderCalendar();
  renderAnnouncements();
  renderCourseContent();
  $("#taskList").hidden = state.view !== "list";
  $("#calendarView").hidden = state.view !== "calendar";
  $("#announcementList").hidden = state.view !== "announcements";
  $("#courseContentList").hidden = state.view !== "content";
  $("#taskHeading").textContent = ({ calendar: "任务日历", announcements: "课程公告", content: "课程内容" })[state.view] || "近期任务";
  document.querySelector('[aria-label="任务状态筛选"]').hidden = ["announcements", "content"].includes(state.view);
}

async function loadData() {
  const response = await apiRequest("/api/data", { cache: "no-store" });
  if (!response.ok) throw new Error("请先选择账号");
  state.data = await response.json();
  if (state.selectionAccount !== state.data.account?.id) {
    state.selectionAccount = state.data.account?.id || null;
    resetCourseSelection(false);
  } else {
    const available = new Set(keysForCourses(state.data.courses));
    state.selectedCourses = new Set([...state.selectedCourses].filter((key) => available.has(key)));
  }
  $("#accountButton span").textContent = state.data.account?.name || "账号";
  $("#materialsButton").hidden = !state.data.account?.sources?.includes("yanhe");
  const stamp = state.data.sources.deadlines_updated_at;
  $("#updatedAt").textContent = stamp ? `更新于 ${new Date(stamp * 1000).toLocaleString("zh-CN", { hour12: false })}` : "尚未更新";
  render();
}

async function refreshData() {
  const button = $("#refreshButton");
  const status = $("#refreshStatus");
  button.disabled = true;
  status.hidden = false;
  status.textContent = "正在后台静默采集…";
  const extras = [...document.querySelectorAll('#refreshDialog input[type="checkbox"]:checked')].map((item) => item.value);
  $("#refreshDialog").close();
  try {
    const response = await apiRequest("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extras }),
    });
    if (!response.ok && response.status !== 409) throw new Error("无法启动刷新");
    const timer = setInterval(async () => {
      const current = await (await apiRequest("/api/status", { cache: "no-store" })).json();
      status.textContent = current.message || "正在刷新…";
      if (current.state === "login" && current.requires_confirmation) {
        $("#accountGate").hidden = false;
        $("#accountStatus").hidden = false;
        $("#accountStatus").textContent = current.message;
        $("#confirmLoginButton").hidden = false;
        $("#confirmLoginButton").disabled = false;
      }
      if (current.state === "complete" || current.state === "error") {
        clearInterval(timer);
        button.disabled = false;
        $("#confirmLoginButton").hidden = true;
        if (current.state === "complete") {
          await loadData();
          $("#accountGate").hidden = true;
        }
        else showFailureNotice(current.message);
      }
    }, 1500);
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
    showFailureNotice(error.message);
  }
}

async function pollAccountWorkflow(showGate = true) {
  const gateStatus = $("#accountStatus");
  const dashboardStatus = $("#refreshStatus");
  gateStatus.hidden = !showGate;
  dashboardStatus.hidden = showGate;
  const timer = setInterval(async () => {
    const current = await (await apiRequest("/api/status", { cache: "no-store" })).json();
    gateStatus.textContent = current.message || "正在准备…";
    dashboardStatus.textContent = current.message || "正在后台刷新…";
    const confirmButton = $("#confirmLoginButton");
    confirmButton.hidden = !(showGate && current.state === "login" && current.requires_confirmation);
    confirmButton.disabled = false;
    if (current.state === "complete") {
      clearInterval(timer);
      confirmButton.hidden = true;
      await loadData();
      $("#accountGate").hidden = true;
      dashboardStatus.textContent = "新任务已加入，列表已更新";
      setTimeout(() => { dashboardStatus.hidden = true; }, 3000);
    } else if (current.state === "error") {
      clearInterval(timer);
      dashboardStatus.textContent = current.message || "后台刷新失败，当前仍显示历史数据";
      showFailureNotice(current.message);
      confirmButton.hidden = true;
    }
  }, 1500);
}

async function confirmLogin() {
  const button = $("#confirmLoginButton");
  button.disabled = true;
  const response = await apiRequest("/api/login/confirm", { method: "POST" });
  const payload = await response.json();
  if (!response.ok) {
    button.disabled = false;
    throw new Error(payload.error || "无法确认认证状态");
  }
  button.hidden = true;
  $("#accountStatus").textContent = "正在验证认证状态…";
}

async function selectAccount(id) {
  const response = await apiRequest("/api/account/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!response.ok) throw new Error("无法选择账号");
  await loadData();
  $("#accountGate").hidden = true;
}

async function createAccount() {
  const name = $("#accountName").value.trim() || "新账号";
  const sources = [
    $("#sourceMooc").checked ? "mooc" : null,
    $("#sourceYanhe").checked ? "yanhe" : null,
  ].filter(Boolean);
  if (!sources.length) throw new Error("请至少选择一个采集平台");
  const response = await apiRequest("/api/account/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, sources }),
  });
  if (!response.ok) throw new Error("无法创建账号");
  pollAccountWorkflow();
}

async function loadAccounts() {
  const response = await apiRequest("/api/accounts", { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "无法读取本地账号");
  $("#savedAccounts").innerHTML = payload.accounts.length
    ? payload.accounts.map((account) => `<button class="saved-account" data-id="${account.id}" type="button"><strong>${escapeHTML(account.name)}</strong><span class="saved-account-meta"><span class="source-badges">${(account.sources || ["mooc", "yanhe"]).map((source) => `<small>${source === "mooc" ? "MOOC" : "延河"}</small>`).join("")}</span><b>›</b></span></button>`).join("")
    : `<div class="empty"><strong>暂无账号</strong></div>`;
  document.querySelectorAll(".saved-account").forEach((button) => button.addEventListener("click", () => selectAccount(button.dataset.id)));
}

async function initializeSecurity() {
  const response = await apiRequest("/api/security", { cache: "no-store" });
  const security = await response.json();
  const locked = !security.unlocked;
  $("#securityUnlock").hidden = !locked;
  $("#accountControls").hidden = locked;
  $("#unlockButton").textContent = security.configured ? "解锁本地数据" : "设置加密密码";
  if (!locked) await loadAccounts();
}

async function unlockLocalData() {
  const password = $("#masterPassword").value;
  const remember = document.querySelector('input[name="rememberUnlock"]:checked')?.value || "none";
  const response = await apiRequest("/api/security/unlock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password, remember }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "无法解锁本地数据");
  $("#masterPassword").value = "";
  $("#securityUnlock").hidden = true;
  $("#accountControls").hidden = false;
  await loadAccounts();
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function updateMaterialSelection() {
  const selected = document.querySelectorAll(".material-checkbox:checked").length;
  $("#materialSelectionCount").textContent = `${selected} 项`;
  $("#downloadSelectedMaterials").disabled = selected === 0;
}

function renderMaterialChoices(items) {
  state.materialItems = items;
  const groups = new Map();
  items.forEach((item) => {
    if (!groups.has(item.course)) groups.set(item.course, []);
    groups.get(item.course).push(item);
  });
  $("#materialsList").innerHTML = items.length ? [...groups.entries()].map(([course, courseItems]) => `
    <section class="material-course">
      <div class="material-course-title"><strong>${escapeHTML(course)}</strong><span>${courseItems.length} 项</span></div>
      ${courseItems.map((item) => `<label class="material-item"><input class="material-checkbox" type="checkbox" value="${escapeHTML(item.reference_id)}" checked><span><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.activity || "课程资料")}${formatBytes(item.size) ? ` · ${formatBytes(item.size)}` : ""}</small></span></label>`).join("")}
    </section>`).join("") : `<div class="empty"><strong>没有可下载的资料</strong></div>`;
  $("#materialsControls").hidden = !items.length;
  $("#materialsScanStatus").textContent = items.length ? `找到 ${items.length} 个文件` : "未找到可下载文件";
  document.querySelectorAll(".material-checkbox").forEach((checkbox) => checkbox.addEventListener("change", updateMaterialSelection));
  updateMaterialSelection();
}

function pollMaterials(onReady) {
  const button = $("#materialsButton");
  const status = $("#refreshStatus");
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const current = await (await apiRequest("/api/materials/status", { cache: "no-store" })).json();
        status.textContent = current.message || "正在处理课程资料…";
        $("#materialsScanStatus").textContent = current.message || "正在扫描…";
        if (["ready", "complete", "error"].includes(current.state)) {
          clearInterval(timer);
          button.disabled = false;
          if (current.state === "error") {
            if ($("#materialsDialog").open) $("#materialsDialog").close();
            showFailureNotice(current.message, "课程资料处理失败");
          } else {
            await onReady(current);
          }
          resolve(current);
        }
      } catch (error) {
        clearInterval(timer);
        button.disabled = false;
        reject(error);
      }
    }, 1000);
  });
}

async function chooseMaterials() {
  const button = $("#materialsButton");
  const status = $("#refreshStatus");
  const dialog = $("#materialsDialog");
  button.disabled = true;
  status.hidden = false;
  status.textContent = "正在扫描课程资料…";
  $("#materialsControls").hidden = true;
  $("#materialsList").innerHTML = "";
  $("#materialsScanStatus").textContent = "正在扫描…";
  if (!dialog.open) dialog.showModal();
  try {
    const response = await apiRequest("/api/materials/scan", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法扫描课程资料");
    await pollMaterials(async (current) => {
      if (current.state === "ready") renderMaterialChoices(current.items || []);
    });
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
    showFailureNotice(error.message, "课程资料扫描失败");
  }
}

async function downloadSelectedMaterials() {
  const referenceIds = [...document.querySelectorAll(".material-checkbox:checked")].map((item) => item.value);
  if (!referenceIds.length) return;
  const button = $("#materialsButton");
  const status = $("#refreshStatus");
  $("#downloadSelectedMaterials").disabled = true;
  button.disabled = true;
  status.hidden = false;
  status.textContent = `正在下载 ${referenceIds.length} 个文件…`;
  $("#materialsDialog").close();
  try {
    const response = await apiRequest("/api/materials/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_ids: referenceIds }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法启动资料下载");
    await pollMaterials(async (current) => {
      if (current.state === "complete") {
        const openResponse = await apiRequest("/api/materials/open", { method: "POST" });
        const openPayload = await openResponse.json();
        if (!openResponse.ok) throw new Error(openPayload.error || "无法打开下载目录");
        setTimeout(() => { status.hidden = true; }, 4000);
      }
    });
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
    showFailureNotice(error.message, "课程资料下载失败");
  }
}

document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".filter").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  state.filter = button.dataset.filter;
  render();
}));
document.querySelectorAll(".view-button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".view-button").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  state.view = button.dataset.view;
  render();
}));
$("#previousMonth").addEventListener("click", () => {
  state.calendarDate = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth() - 1, 1);
  renderCalendar();
});
$("#nextMonth").addEventListener("click", () => {
  state.calendarDate = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth() + 1, 1);
  renderCalendar();
});
$("#refreshButton").addEventListener("click", () => $("#refreshDialog").showModal());
$("#resetCourseSelection").addEventListener("click", () => resetCourseSelection());
$("#closeRefreshDialog").addEventListener("click", () => $("#refreshDialog").close());
$("#cancelRefresh").addEventListener("click", () => $("#refreshDialog").close());
$("#startRefresh").addEventListener("click", refreshData);
$("#materialsButton").addEventListener("click", chooseMaterials);
$("#closeMaterialsDialog").addEventListener("click", () => $("#materialsDialog").close());
$("#cancelMaterials").addEventListener("click", () => $("#materialsDialog").close());
$("#selectAllMaterials").addEventListener("click", () => { document.querySelectorAll(".material-checkbox").forEach((item) => { item.checked = true; }); updateMaterialSelection(); });
$("#clearAllMaterials").addEventListener("click", () => { document.querySelectorAll(".material-checkbox").forEach((item) => { item.checked = false; }); updateMaterialSelection(); });
$("#downloadSelectedMaterials").addEventListener("click", downloadSelectedMaterials);
$("#closeFailureNotice").addEventListener("click", () => $("#failureNotice").close());
$("#newAccountButton").addEventListener("click", () => createAccount().catch((error) => {
  $("#accountStatus").hidden = false;
  $("#accountStatus").textContent = error.message;
}));
$("#confirmLoginButton").addEventListener("click", () => confirmLogin().catch((error) => {
  showFailureNotice(error.message, "认证确认失败");
}));
$("#unlockButton").addEventListener("click", () => unlockLocalData().catch((error) => {
  $("#accountStatus").hidden = false;
  $("#accountStatus").textContent = error.message;
}));
$("#masterPassword").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("#unlockButton").click();
});
$("#accountButton").addEventListener("click", () => {
  $("#accountGate").hidden = false;
  loadAccounts();
});
$("#closeAccountGate").addEventListener("click", () => { $("#accountGate").hidden = true; });
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("#accountGate").hidden = true;
});
$("#exportButton").addEventListener("click", (event) => {
  event.stopPropagation();
  $("#exportOptions").hidden = !$("#exportOptions").hidden;
});
document.addEventListener("click", () => { $("#exportOptions").hidden = true; });
$("#exportOptions").addEventListener("click", (event) => event.stopPropagation());
document.querySelectorAll(".export-option").forEach((button) => button.addEventListener("click", async () => {
  if (window.pywebview?.api) {
    const result = await window.pywebview.api.export_data(button.dataset.format);
    alert(result.ok ? `已导出到：${result.payload.path}` : result.payload.error);
  } else {
    window.location.href = `/api/export?format=${button.dataset.format}`;
  }
  $("#exportOptions").hidden = true;
}));
function initialize() {
  initializeSecurity().catch((error) => {
    $("#accountStatus").hidden = false;
    $("#accountStatus").textContent = error.message || "无法读取本地账号";
  });
}

if (location.protocol === "file:" && !window.pywebview?.api) {
  window.addEventListener("pywebviewready", initialize, { once: true });
} else {
  initialize();
}
