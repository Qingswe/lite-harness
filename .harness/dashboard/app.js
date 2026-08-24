const COLS = ["状态", "步骤与判定契约", "操作者", "日期", "备注"];
const PHASES = {
  planned: { label:"已规划", cls:"cand", dot:"cand" },
  implementing: { label:"实施中", cls:"active", dot:"active" },
  auto_verified: { label:"自动验证完成", cls:"ready", dot:"ready" },
  awaiting_human: { label:"待人工检查", cls:"await", dot:"await" },
  awaiting_user_direction: { label:"待用户指示", cls:"await", dot:"await" },
  awaiting_human_and_user_direction: { label:"待人工检查 + 用户指示", cls:"await", dot:"await" },
  ready_to_close: { label:"可关闭（harness close）", cls:"ready", dot:"ready" },
  blocked: { label:"受阻", cls:"blocked", dot:"blocked" },
  complete: { label:"任务完成", cls:"ready", dot:"done" },
};
let STATE = null;
// 当前选中的视图：{type:"overview"} | {type:"change", id} | {type:"library", key}
let activeView = { type: "overview" };
let firstRender = true;

function el(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) {
    if (k === "class") e.className = attrs[k];
    else if (k === "text") e.textContent = attrs[k];
    else if (k === "html") e.innerHTML = attrs[k];
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]);
    else e.setAttribute(k, attrs[k]);
  }
  (children || []).forEach(c => c && e.appendChild(c));
  return e;
}
function toast(msg, kind) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "show " + (kind || "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = ""; }, kind === "err" ? 4000 : 1600);
}
async function api(path, body) {
  const res = await fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}
async function load() {
  const res = await fetch("/api/state");
  STATE = await res.json();
  if (firstRender) {  // 首次默认选中 active change（若有），否则概览
    const act = STATE.changes.find(c => c.is_active);
    if (act) activeView = { type: "change", id: act.id };
    firstRender = false;
  }
  // 选中的 change 若已不存在，回退到概览
  if (activeView.type === "change" && !STATE.changes.some(c => c.id === activeView.id))
    activeView = { type: "overview" };
  // 选中的节点若已不存在，回退到概览
  if (!navKeys().has(viewKey(activeView))) activeView = { type: "overview" };
  render();
}
// 视图与导航节点的对应关系：一个视图就是树里的一个 key。
function viewKey(view) {
  if (view.type === "overview") return "overview";
  if (view.type === "change") return "change:" + view.id;
  if (view.type === "doc") return "doc:" + view.path;
  // change 为空 = 「全部证据」，键用 * ——与 build_nav_tree() 给的键一致，
  // 否则 navKeys() 找不到它，视图会被弹回概览。
  if (view.type === "evidence") return "evidence:" + (view.change || "*");
  if (view.type === "feature_index") return "library/feature_index";
  if (view.type === "system") return "library/system";
  return "";
}
function navKeys() {
  const keys = new Set();
  (function walk(nodes) {
    (nodes || []).forEach(n => { keys.add(n.key); walk(n.children); });
  })(STATE.nav_tree);
  return keys;
}
function viewForNode(node) {
  switch (node.kind) {
    case "overview": return { type: "overview" };
    case "change": return { type: "change", id: node.change };
    case "doc": return { type: "doc", path: node.doc_path, title: node.label };
    case "evidence": return { type: "evidence", change: node.change };
    case "feature_index": return { type: "feature_index" };
    case "system": return { type: "system" };
    default: return null;
  }
}
function fmtSize(n){ return n < 1024 ? n+" B" : (n/1024).toFixed(1)+" KB"; }
function phaseMeta(ch) {
  return PHASES[ch.lifecycle_phase] || { label: ch.lifecycle_phase || "未知阶段", cls:"cand", dot:"" };
}
function phasePill(ch) {
  const p = phaseMeta(ch);
  return el("span", { class:"pill " + p.cls, text:p.label });
}
function changeLink(id) {
  const link = el("span", { class:"queue-link", text:id });
  if (STATE.changes.some(ch => ch.id === id))
    link.addEventListener("click", () => navTo({ type:"change", id }));
  return link;
}

function navTo(view) {
  activeView = view;
  document.getElementById("app").classList.remove("nav-open"); // 移动端选完收起
  render();
  document.querySelector("main.content").scrollTop = 0;
}

function render() {
  renderNav();
  renderContent();
  renderRoleSwitch();
  document.getElementById("meta").textContent =
    "更新于 " + (STATE.current.last_updated || "—");
}

// 侧栏底部的角色切换。它只决定「预填谁」，不决定「谁做的判定」——
// evaluated_by 从不经过看板这条路径，切换角色改不了任何已写下的结论。
function renderRoleSwitch() {
  const box = document.getElementById("roleSwitch");
  box.innerHTML = "";
  const roles = STATE.roles;
  if (!roles || !roles.profiles || !roles.profiles.length) {
    if (roles && roles.error)
      box.appendChild(el("div", { class: "empty", text: "角色档案不可用：" + roles.error }));
    return;
  }
  box.appendChild(el("span", { class: "role-cap", text: "当前角色" }));
  const sel = el("select", { class: "cell" });
  roles.profiles.forEach(p => {
    // 只显示 label：档案的 label 本来就是给人读的，再拼一次 operator 会得到
    // `张三（人工）（zhangsan）` 这种重复。
    const o = el("option", { value: p.id, text: p.label });
    if (p.id === roles.active_profile) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", async () => {
    const { res, data } = await api("/api/roles", { action: "use", profile: sel.value });
    if (!res.ok) { toast("切换失败: " + (data.error || res.status), "err"); return; }
    STATE.roles = data.roles;
    toast("已切换到 " + sel.value, "ok");
    render();               // 重渲染让步骤行的预填跟着变
  });
  box.appendChild(sel);
}

// ====================================================================
//  左侧边栏导航
// ====================================================================
function renderNav() {
  const nav = document.getElementById("nav");
  nav.innerHTML = "";
  (STATE.nav_tree || []).forEach(node => nav.appendChild(navNode(node)));
}

// 展开状态是显示偏好，不是可恢复状态，所以只存浏览器本地，不写 current.json。
const OPEN_KEY = "harness-board-open";
function openSet() {
  try { return new Set(JSON.parse(localStorage.getItem(OPEN_KEY)) || []); }
  catch (e) { return new Set(); }
}
function rememberOpen(key, open) {
  const set = openSet();
  open ? set.add(key) : set.delete(key);
  try { localStorage.setItem(OPEN_KEY, JSON.stringify([...set])); } catch (e) {}
}
function isOpen(node) {
  const stored = localStorage.getItem(OPEN_KEY);
  if (stored === null) return node.initial_expanded;   // 首次加载：按服务端给的首屏策略
  return openSet().has(node.key);
}

// \u56FE\u6807\u5168\u90E8\u53D6\u81EA\u540C\u4E00\u5957\u51E0\u4F55\u7B26\u53F7\uFF0C\u5B57\u53F7\u4E0E\u989C\u8272\u7531 .nav-ico \u7EDF\u4E00\u63A7\u5236\u3002\u4E0D\u7528 emoji\uFF1A
// emoji \u7531\u7CFB\u7EDF\u5B57\u4F53\u6E32\u67D3\uFF0C\u5BBD\u5EA6\u3001\u57FA\u7EBF\u548C\u989C\u8272\u90FD\u4E0D\u53D7 theme.css \u7BA1\uFF0C\u6DF7\u5728\u4E00\u5957\u5B9A\u597D\u4E86
// \u5B57\u53F7\u4E0E\u884C\u9AD8\u7684\u6392\u7248\u91CC\u5C31\u662F\u51E0\u4E2A\u5927\u5C0F\u4E0D\u4E00\u7684\u5F69\u8272\u8272\u5757\u3002
const NAV_ICONS = {
  overview: "\u25A3", group: "", feature_index: "\u25A6",
  doc: "\u25AB", evidence: "\u25C7", change: "",
};

function navNode(node) {
  if (!node.children || !node.children.length) return navLeaf(node);
  const d = el("details", { class: "nav-branch" });
  if (isOpen(node)) d.open = true;
  const label = [el("span", { class: "nav-title", text: node.label })];
  if (node.count != null) label.push(el("span", { class: "nav-sub", text: String(node.count) }));
  d.appendChild(el("summary", { class: "nav-summary d" + node.depth }, label));
  const box = el("div", { class: "nav-children" });
  node.children.forEach(child => box.appendChild(navNode(child)));
  d.appendChild(box);
  d.addEventListener("toggle", () => rememberOpen(node.key, d.open));
  return d;
}

function navLeaf(node) {
  const view = viewForNode(node);
  const kids = [];
  if (node.kind === "change") kids.push(el("span", { class: "nav-dot " + (node.dot || "") }));
  else kids.push(el("span", { class: "nav-ico", text: NAV_ICONS[node.kind] || "\u25AB" }));
  kids.push(el("span", { class: "nav-title", text: node.label, title: node.label }));
  const p = node.progress;
  if (p && p.total) kids.push(el("span", { class: "nav-sub", text: p.done + "/" + p.total }));
  else if (node.count != null) kids.push(el("span", { class: "nav-sub", text: String(node.count) }));
  const selected = viewKey(activeView) === node.key;
  return el("div", {
    class: "nav-item d" + node.depth + (selected ? " sel" : ""),
    onclick: () => { if (view) navTo(view); },
  }, kids);
}

// ====================================================================
//  右侧内容区
// ====================================================================
function renderContent() {
  const box = document.getElementById("content");
  box.innerHTML = "";
  if (activeView.type === "overview") return renderOverview(box);
  if (activeView.type === "feature_index") return renderFeatureIndex(box);
  if (activeView.type === "system") return renderSystemPage(box);
  if (activeView.type === "doc") return renderDocPage(box, activeView);
  if (activeView.type === "evidence") return renderEvidencePage(box, activeView.change);
  if (activeView.type === "change") {
    const ch = STATE.changes.find(c => c.id === activeView.id);
    if (ch) return renderChangeDetail(box, ch);
  }
  box.appendChild(el("div", { class: "empty", text: "未找到内容。" }));
}

// ---------- 概览（current.json） ----------
const OWNER_LABEL = { human: "人", ai: "AI", external: "外部" };

async function loadReadyInto(box) {
  let data;
  try {
    const res = await fetch("/api/ready");
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || res.status);
  } catch (e) {
    box.lastChild.replaceWith(el("div", { class: "notice error", text: "就绪度载入失败： " + e.message }));
    return;
  }
  const holder = el("div");
  holder.appendChild(el("div", { class: "section-title" }, [
    el("span", { text: "可归档（" + data.ready.length + "）" })]));
  if (data.ready.length) {
    data.ready.forEach(item => {
      const deps = (item.depends_on || []);
      holder.appendChild(el("div", { class: "candidate-entry" }, [
        el("div", { class: "candidate-head" }, [
          changeLink(item.change),
          el("span", { class: "pill ready", text: deps.length ? "依赖 " + deps.join("、") : "依赖已满足" }),
        ]),
      ]));
    });
  } else {
    holder.appendChild(el("div", { class: "empty", text: "无" }));
  }
  holder.appendChild(el("div", { class: "section-title" }, [
    el("span", { text: "被阻塞（" + data.blocked.length + "）" })]));
  data.blocked.forEach(item => {
    holder.appendChild(el("div", { class: "candidate-entry" }, [
      el("div", { class: "candidate-head" }, [
        changeLink(item.change),
        el("span", { class: "pill " + (item.owner === "human" ? "await" : "cand"),
                     text: "[" + (OWNER_LABEL[item.owner] || item.owner) + "]" }),
      ]),
      // 只列差的那一件事：人需要的是下一个动作，不是清单。
      el("div", { class: "candidate-summary", text: item.next_action }),
    ]));
  });
  box.lastChild.replaceWith(holder);
}

function renderOverview(box) {
  const c = STATE.current;
  pageHeader(box, { title: "概览",
    sub: ".harness/current.json · schema v" + (c.schema_version || "?") });

  (c.state_errors || []).forEach(msg =>
    box.appendChild(el("div", { class:"notice error", text:"状态错误： " + msg })));
  if (c.migration_pending) {
    const text = (c.migration_warnings || []).length
      ? `检测到 ${c.migration_warnings.length} 条 legacy 状态；下一次有意的 current 写入将迁移为 schema v2。`
      : "检测到 legacy current 状态；下一次有意写入将迁移为 schema v2。";
    box.appendChild(el("div", { class:"notice", text }));
  }

  const queues = STATE.queues || {};
  const queueDefs = [
    ["active", "唯一执行槽"],
    ["awaiting_human", "待人工检查"],
    ["awaiting_user_direction", "待用户指示"],
    ["ready_to_close", "可关闭"],
    ["planned_candidates", "已规划候选"],
  ];
  const queueGrid = el("div", { class:"queue-grid" });
  queueDefs.forEach(([key, label]) => {
    const ids = queues[key] || [];
    const cell = el("div", { class:"queue-card" });
    // 数字比标签重要：先给一个大号计数，再列具体是哪几个。
    cell.appendChild(el("div", { class:"queue-title", text:label }));
    cell.appendChild(el("span", { class:"queue-count", text:String(ids.length) }));
    const items = el("div", { class:"queue-items" });
    if (ids.length) ids.forEach(id => items.appendChild(changeLink(id)));
    else items.appendChild(el("span", { class:"empty", text:"—" }));
    cell.appendChild(items);
    queueGrid.appendChild(cell);
  });
  box.appendChild(queueGrid);

  // 归档就绪度：数据来自 /api/ready，与 `harness ready` 同一份实现。
  const readyBox = card(box, "归档就绪度", "与 harness ready 同源");
  readyBox.appendChild(el("div", { class: "empty", text: "载入中…" }));
  loadReadyInto(readyBox);

  const b = card(box, "当前恢复点");
  b.appendChild(row("执行中", [ c.active_change
    ? changeLink(c.active_change)
    : el("span", { class: "pill none", text:
        ((queues.awaiting_human||[]).length || (queues.awaiting_user_direction||[]).length)
          ? "执行槽有意释放；待办已保存在下方阶段队列"
          : "无 active change" }) ]));
  if (c.active_change)
    b.appendChild(row("操作", [currentButton("释放 active", "clear-active", null)]));
  if (c.current_task) b.appendChild(row("当前任务", [el("span", { class:"cid", text: c.current_task })]));
  if (c.last_verified_task) b.appendChild(row("上次验证", [el("span", { class:"cid", text: c.last_verified_task })]));
  if (c.blockers && c.blockers.length)
    b.appendChild(row("阻塞", c.blockers.map(x => el("div", { class: "blockers", text: "• " + x }))));
  if (c.next_action) b.appendChild(row("下一步", [el("span", { text: c.next_action })]));
  if (c.verification_summary) {
    const v = c.verification_summary;
    const vkids = [];
    if (v.phase) vkids.push(el("div", { class:"summary-block", text:"阶段： " + v.phase }));
    if (v.auto_verification) vkids.push(el("div", { class:"summary-block", text:"自动验证： " + v.auto_verification }));
    if (v.playmode_attempt) vkids.push(el("div", { class:"summary-block", text:"Play 验证： " + v.playmode_attempt }));
    if (v.human_checks) vkids.push(el("div", { class:"summary-block", text:"人工检查： " + v.human_checks }));
    if (vkids.length) b.appendChild(row("验证摘要", vkids));
  }
  if (c.candidate_changes && c.candidate_changes.length) {
    const list = el("div", { class:"candidate-list" });
    c.candidate_changes.forEach(id => {
      const ch = STATE.changes.find(x => x.id === id);
      const item = el("div", { class:"candidate-entry" });
      const head = el("div", { class:"candidate-head" }, [changeLink(id)]);
      if (ch) {
        head.appendChild(el("span", { class:"pill cand", text:"候选" }));
        head.appendChild(phasePill(ch));
      }
      item.appendChild(head);
      if (ch && ch.summary)
        item.appendChild(el("div", { class:"candidate-summary", text:ch.summary }));
      list.appendChild(item);
    });
    b.appendChild(row("候选", [list]));
  }
  if (c.session_wrap_up && c.session_wrap_up.archived && c.session_wrap_up.archived.length)
    b.appendChild(row("已归档", c.session_wrap_up.archived.map(id => el("span", { class: "pill arch", text: id }))));
  if (c.parse_error) b.appendChild(row("JSON 解析", [el("span", { class: "blockers", text: c.parse_error })]));
  if (c.migration_warnings && c.migration_warnings.length)
    b.appendChild(fold("迁移详情 (" + c.migration_warnings.length + ")",
      el("div", { class:"mono-list" }, c.migration_warnings.map(x => el("div", { text:"• " + x })))));

  // 可折叠：工作文件 / 脏假设 / 检查点
  if (c.working_files && c.working_files.length)
    b.appendChild(fold("工作文件 (" + c.working_files.length + ")",
      el("div", { class: "mono-list" }, c.working_files.map(f => el("div", { text: f })))));
  if (c.dirty_assumptions && c.dirty_assumptions.length)
    b.appendChild(fold("脏假设 (" + c.dirty_assumptions.length + ")",
      el("div", {}, c.dirty_assumptions.map(a => el("div", { text: "• " + a })))));
  if (c.last_checkpoint) {
    const cpHolder = el("div");
    b.appendChild(fold("最近检查点 · " + c.last_checkpoint, cpHolder,
      () => loadDocInto(c.last_checkpoint, cpHolder)));
  }

  const graphs = STATE.graphs || {};
  graphSection(box, "归档依赖", graphs.dependency, "来自 change_context 的 depends_on");

  if (!STATE.changes.length)
    box.appendChild(el("div", { class: "empty", text: "openspec/changes/ 下暂无 change。" }));
}
function row(label, children) {
  const r = el("div", { class: "row" });
  r.appendChild(el("span", { class: "label", text: label }));
  // 间距走 .row-values 的 var(--s1)，不写内联样式：内联样式里的 px 绕过
  // theme.css，8px 栅格断言看不见它们。
  const wrap = el("div", { class: "row-values" });
  children.forEach(ch => wrap.appendChild(ch));
  r.appendChild(wrap);
  return r;
}

// ---------- 页头与卡片 ----------
// 标题、标识、状态、进度、操作是同一件事的五个侧面，关进同一个块里，用一条
// 分隔线和正文断开；正文再按内容切成若干张卡，每张卡的头写明这块是什么、有
// 多少条。改造前这些全都平铺在页面上，一个 change 详情页只有一个巨型面板。
function pageHeader(box, opts) {
  const head = el("div", { class: "page-header" });
  head.appendChild(el("h1", { class: "page-title", text: opts.title }));
  if (opts.sub) head.appendChild(el("div", { class: "page-sub", text: opts.sub }));
  if ((opts.tags || []).length)
    head.appendChild(el("div", { class: "page-tags" }, opts.tags));
  if ((opts.meta || []).length)
    head.appendChild(el("div", { class: "page-meta" }, opts.meta));
  box.appendChild(head);
  return head;
}

function card(box, title, meta, active) {
  const c = el("div", { class: "card" + (active ? " active" : "") });
  const head = el("div", { class: "card-head" },
    [el("h2", { class: "card-title", text: title })]);
  if (meta) head.appendChild(meta.nodeType
    ? meta : el("span", { class: "card-meta", text: String(meta) }));
  c.appendChild(head);
  const body = el("div", { class: "card-body" });
  c.appendChild(body);
  box.appendChild(c);
  return body;
}
function fold(summaryText, contentEl, onOpen) {
  const d = el("details", { class: "fold" });
  d.appendChild(el("summary", { text: summaryText }));
  d.appendChild(contentEl);
  if (onOpen) d.addEventListener("toggle", () => { if (d.open) onOpen(); }, { once: true });
  return d;
}
function currentButton(text, action, change) {
  return el("button", { class: "btn", text, onclick: async () => {
    const { res, data } = await api("/api/current", { action, change });
    if (!res.ok) { toast("操作失败: " + (data.error || res.status), "err"); return; }
    toast("已更新 current.json", "ok");
    await load();
  }});
}

// ---------- change 详情 ----------
function renderChangeDetail(box, ch) {
  const tags = [];
  if (ch.is_active) tags.push(el("span", { class: "pill active", text: "执行中" }));
  if (ch.is_candidate) tags.push(el("span", { class: "pill cand", text: "候选" }));
  tags.push(phasePill(ch));
  if (ch.phase_source === "derived")
    tags.push(el("span", { class: "pill none", text: "阶段为保守推导" }));

  const p = ch.task_progress;
  const pct = p.total ? Math.round(p.done / p.total * 100) : 0;
  const bar = el("i");
  bar.style.width = pct + "%";     // 唯一按数据算的样式，其余一律走 class
  const num = el("span", { class: "num", text: p.done + "/" + p.total });
  const progress = el("div", { class: "progress" }, [
    el("span", { class: "cap", text: "任务" }),
    el("div", { class: "bar" }, [bar]), num,
  ]);

  pageHeader(box, {
    title: ch.title, sub: ch.id, tags,
    meta: [progress, renderChangeActions(ch)],
  });

  (ch.lifecycle_warnings || []).forEach(msg =>
    box.appendChild(el("div", { class: "notice error", text: "阶段矛盾： " + msg })));

  // 摘要与恢复点：只在有内容时成卡，不留空壳。
  const recovery = ch.recovery || {};
  const hasBrief = ch.summary || (recovery.blockers || []).length
    || recovery.next_action || recovery.last_checkpoint;
  if (hasBrief) {
    const brief = card(box, "这个变更在做什么");
    if (ch.summary)
      brief.appendChild(el("div", { class: "summary-block", text: ch.summary }));
    if ((recovery.blockers || []).length)
      brief.appendChild(row("阶段阻塞", recovery.blockers.map(x =>
        el("div", { class: "blockers", text: "• " + x }))));
    if (recovery.next_action)
      brief.appendChild(row("恢复动作", [el("span", { text: recovery.next_action })]));
    if (recovery.last_checkpoint) {
      const holder = el("div");
      brief.appendChild(fold("恢复检查点 · " + recovery.last_checkpoint, holder,
        () => loadDocInto(recovery.last_checkpoint, holder)));
    }
  }

  const tasks = card(box, "任务", p.total ? p.done + " / " + p.total + " 已完成" : null,
                     ch.is_active);
  if (!ch.has_tasks) tasks.appendChild(el("div", { class: "empty", text: "未创建 tasks.md" }));
  else tasks.appendChild(renderTasks(ch, bar, num));

  const cc = ch.check_counts || {};
  const counts = el("span", { class: "card-meta", html:
    `<span class="dot passed"></span>${cc.passed||0} <span class="dot pending"></span>${cc.pending||0} <span class="dot failed"></span>${cc.failed||0} <span class="dot waived"></span>${cc.waived||0}` });
  const checks = card(box, "验证步骤", counts);
  if (ch.verification_error) {
    // 解析不了必须说出来，不能显示成"没有未完成项"。
    checks.appendChild(el("div", { class: "notice error", text: "验证记录不可解析： " + ch.verification_error }));
  } else if (!ch.steps || !ch.steps.length) {
    checks.appendChild(el("div", { class: "empty", text: "无验证步骤" }));
  } else {
    checks.appendChild(renderFlowFigure(ch));
    const human = ch.steps.filter(s => s.role === "human");
    const auto = ch.steps.filter(s => s.role !== "human");
    if (human.length) {
      checks.appendChild(el("div", { class: "section-title" },
        [el("span", { class: "role-human", text: "需要人（" + human.length + "）" })]));
      checks.appendChild(renderSteps(ch, human));
    }
    if (auto.length) {
      checks.appendChild(el("div", { class: "section-title" },
        [el("span", { text: "自动验证（" + auto.length + "）" })]));
      checks.appendChild(renderSteps(ch, auto));
    }
  }

  // 只读预览：验证记录 / 检查点 / 证据
  const files = [];
  if (ch.verification) files.push(["验证记录", ch.program || ch.verification, "program.md"]);
  (ch.checkpoints || []).forEach((cp, i) =>
    files.push([i === 0 ? "最新检查点" : "检查点", cp, cp.split("/").pop()]));
  if (files.length || (ch.evidence || []).length) {
    const docs = card(box, "相关文件",
      (ch.evidence || []).length ? (ch.evidence.length + " 份证据") : null);
    files.forEach(([kind, path, name]) => {
      const holder = el("div");
      docs.appendChild(fold(kind + " · " + name, holder,
        () => loadDocInto(path, holder)));
    });
    if ((ch.evidence || []).length) {
      docs.appendChild(el("div", { class: "section-title" },
        [el("span", { text: "证据（" + ch.evidence.length + "）" })]));
      ch.evidence.forEach(e => docs.appendChild(docLine(e.path, e.size)));
    }
  }
}
// ---------- 关系图 ----------
// 三张图的关系都由源数据算出（change_context 的 depends_on、server.py 的
// DATA_FLOW、ast 解析的 import），不手绘：手绘的架构图会漂移，而漂移的图比没有
// 图更糟，它让人对着一个不再成立的结构做决定。
function renderGraphFigure(graph, title) {
  const fig = el("figure", { class: "figure" });
  if (!graph || !graph.nodes || !graph.nodes.length) {
    fig.appendChild(el("div", { class: "empty", text: title + "：暂无可画的关系。" }));
    return fig;
  }
  // 文字降级先进 DOM，理由同验证流程图。
  const ol = el("ol", { class: "flow-steps" });
  graph.edges.forEach(e => {
    const from = graph.nodes.find(n => n.id === e.from);
    const to = graph.nodes.find(n => n.id === e.to);
    if (!from || !to) return;
    ol.appendChild(el("li", { class: "flow-step" }, [
      el("span", { class: "flow-step-head", text: from.label + " → " + to.label }),
      el("span", { class: "flow-step-body", text: EDGE_LABEL(e.kind) }),
    ]));
  });
  const fold_ = fold("关系清单（" + graph.edges.length + " 条，图形不可读时看这里）", ol);
  fig.appendChild(fold_);
  fig.appendChild(el("figcaption", { text: graph.caption || "" }));
  try {
    const svg = window.HarnessGraph && window.HarnessGraph.render(graph, { title });
    if (svg) fig.insertBefore(svg, fold_);
  } catch (e) {
    fig.insertBefore(el("div", { class: "notice",
      text: "图形未能渲染，下面的关系清单是完整的： " + e.message }), fold_);
  }
  return fig;
}
const EDGE_LABEL = k => ({
  covers: "这条规则决定该步骤怎么算通过",
  settles: "该步骤有结论后才谈得上归档",
  blocks: "前者必须先归档，后者才能归档",
  reads: "该端点读这个文件",
  writes: "该端点写这个文件",
  imports: "前者直接 import 后者，依赖它的实现",
})[k] || k;

function graphSection(box, title, graph, note) {
  card(box, title, note).appendChild(renderGraphFigure(graph, title));
}

// ---------- 验证流程图 + 文字降级 ----------
// 「图形渲染失败时仍能完整理解流程」不能靠把摘要塞进 <details>，也不能让它和图
// 由同一段代码产出——图挂了摘要多半一起挂。所以 <ol> 先无条件进 DOM，图形再
// 在 try 里尝试插到它前面：render 抛异常时 insertBefore 根本执行不到，<ol> 原样
// 留着。
function renderFlowFigure(ch) {
  const flow = ch.verification_flow || { nodes: [], edges: [], caption: "" };
  const fig = el("figure", { class: "figure" });

  const ol = el("ol", { class: "flow-steps" });
  ch.steps.forEach(s => {
    const li = el("li", { class: "flow-step s-" + s.status });
    li.appendChild(el("span", { class: "flow-step-head",
      text: s.id + " · " + STATUS_LABEL(s.status) + " · " + ROLE_LABEL(s.role) }));
    li.appendChild(el("span", { class: "flow-step-body",
      text: "通过： " + (s.pass_when || s.item || "—") }));
    ol.appendChild(li);
  });
  fig.appendChild(ol);
  fig.appendChild(el("figcaption", { text: flow.caption ||
    "箭头从评估规则指向引用它的验证步骤，再指向归档结论。" }));

  try {
    const svg = window.HarnessGraph && window.HarnessGraph.render(flow,
      { title: "验证流程：" + ch.id });
    if (svg) fig.insertBefore(svg, ol);
  } catch (e) {
    fig.insertBefore(el("div", { class: "notice",
      text: "流程图未能渲染，下面的文字步骤是完整的： " + e.message }), ol);
  }
  return fig;
}
const STATUS_LABEL = s => ({ passed:"已通过", pending:"待处理",
  failed:"失败", waived:"已豁免" })[s] || s || "未知";
const ROLE_LABEL = r => ({ human:"需要人", evaluator:"自动验证",
  external:"外部" })[r] || r || "未标注角色";

function renderChangeActions(ch) {
  const actions = [];
  if (ch.is_active) {
    actions.push(currentButton("释放 active", "clear-active", null));
  } else {
    actions.push(currentButton("设为 active", "set-active", ch.id));
    actions.push(ch.is_candidate
      ? currentButton("移出候选", "remove-candidate", ch.id)
      : currentButton("加入候选", "add-candidate", ch.id));
  }
  if (ch.lifecycle_phase === "ready_to_close")
    actions.push(el("span", { class:"pill ready", text:"请使用 harness close；看板不直接归档" }));
  return el("div", { class: "actions" }, actions);
}
function renderTasks(ch, bar, num) {
  const ul = el("ul", { class: "tasks" });
  ch.tasks.forEach(t => {
    if (t.type === "heading") {
      // 一级标题是 tasks.md 的文件名标题（`# Tasks — <id>`），和页面大标题
      // 说的是同一件事，重复一遍只是占地方。
      if (t.level === 1) return;
      ul.appendChild(el("li", { class: "heading", text: t.text }));
      return;
    }
    const cb = el("input", { type: "checkbox" }); cb.checked = t.checked;
    const li = el("li", { class: t.checked ? "done" : "" }, [ cb, el("span", { class: "txt", text: t.text }) ]);
    if (t.indent) li.style.paddingLeft = (t.indent * 1.2) + "em";
    cb.addEventListener("change", async () => {
      cb.disabled = true;
      const { res, data } = await api("/api/task",
        { change: ch.id, line: t.line, checked: cb.checked, expected: t.raw });
      cb.disabled = false;
      if (res.status === 409) { toast("文件已被外部修改，正在刷新…", "err"); return load(); }
      if (!res.ok) { toast("保存失败: " + (data.error || res.status), "err"); cb.checked = t.checked; return; }
      // 就地更新，不重渲染（保持展开与滚动位置）
      t.checked = cb.checked; t.raw = data.line;
      li.classList.toggle("done", cb.checked);
      const tasks = ch.tasks.filter(x => x.type === "task");
      ch.task_progress.done = tasks.filter(x => x.checked).length;
      const pct = ch.task_progress.total ? Math.round(ch.task_progress.done / ch.task_progress.total * 100) : 0;
      bar.style.width = pct + "%";
      num.textContent = ch.task_progress.done + "/" + ch.task_progress.total;
      toast("已保存", "ok");
    });
    ul.appendChild(li);
  });
  return ul;
}
function renderSteps(ch, steps) {
  const table = el("table", { class: "checks" });
  table.appendChild(el("tr", {}, COLS.map(c => el("th", { text: c }))));
  steps.forEach(s => table.appendChild(renderStepRow(ch, s)));
  return table;
}
function renderStepRow(ch, r) {
  const tr = el("tr");
  const state = { status: r.status, operator: r.operator, date: r.date, notes: r.notes };
  async function save() {
    // 按 step id 寻址，冲突以状态比对判定；不再携带原始整行。
    const { res, data } = await api("/api/verification-step", {
      change: ch.id, step: r.id, expected: r.status,
      status: state.status, operator: state.operator, date: state.date, notes: state.notes });
    if (res.status === 409) { toast("步骤已被外部修改，正在刷新…", "err"); return load(); }
    if (!res.ok) { toast("保存失败: " + (data.error || res.status), "err"); return; }
    r.status = state.status; r.operator = state.operator;
    r.date = state.date; r.notes = state.notes; toast("已保存", "ok");
  }
  const sel = el("select", { class: "status s-" + r.status });
  STATE.statuses.forEach(s => {
    const o = el("option", { value: s, text: s }); if (s === r.status) o.selected = true; sel.appendChild(o);
  });
  sel.addEventListener("change", () => { state.status = sel.value; sel.className = "status s-" + sel.value; save(); });
  tr.appendChild(el("td", {}, [sel]));

  // 判定契约直接摆在作答处：人不该为了回答一个检查项去回读设计文档。
  const item = el("td", { class: "item" });
  item.appendChild(el("div", { class: "step-id", text: r.id + (r.rule ? " · " + r.rule : "") }));
  if (r.observe) item.appendChild(el("div", { class: "criterion", text: "观察： " + r.observe }));
  item.appendChild(el("div", { class: "criterion pass", text: "通过： " + (r.item || "—") }));
  if (r.fail_when) item.appendChild(el("div", { class: "criterion fail", text: "失败： " + r.fail_when }));
  if (r.needs_human_because) item.appendChild(el("div", { class: "criterion why", text: "需人： " + r.needs_human_because }));
  if (r.evidence && r.evidence.length) item.appendChild(el("div", { class: "criterion", text: "证据： " + r.evidence.join("、") }));
  tr.appendChild(item);

  // 操作者从维护好的角色档案里**选**，不手敲。预填只解决「不用打字」，选择才
  // 解决「不用记得有哪些人」——档案本来就是为这件事维护的。
  // 只在字段为空时预填：已有值的步骤再次保存必须原样保留，否则一次无关的状态
  // 修改会把历史记录里的操作者悄悄改成当前档案。
  const opCell = operatorPicker(r.operator || operatorFor(r.role),
                                v => state.operator = v, save);
  if (!r.operator) state.operator = opCell.value();
  tr.appendChild(el("td", {}, [opCell.node]));

  const dateInput = el("input", { class: "cell", value: r.date || localToday() });
  if (!r.date) state.date = dateInput.value;
  dateInput.addEventListener("change", () => { state.date = dateInput.value; save(); });
  const today = el("button", { class: "btn", text: "今天", onclick: () => {
    dateInput.value = localToday(); state.date = dateInput.value; save(); }});
  tr.appendChild(el("td", {}, [el("div", { class: "date-wrap" }, [dateInput, today])]));

  const noteInput = textCell(r.notes, v => state.notes = v, save);
  const tpl = noteTemplate();
  // 模板只作为 placeholder：它是提示，不是已填写的理由。waived 仍然要求真的
  // 写点什么，服务端也会再拒一次空备注。
  if (!r.notes && tpl) noteInput.placeholder = tpl;
  tr.appendChild(el("td", {}, [noteInput]));
  return tr;
}
// 本地日历日期。**不用 toISOString()**：那给的是 UTC 日期，在 UTC+8 的晚上
// 8 点之后会填成昨天——一个在开发者所在时区永远不复现的 bug。
function localToday() {
  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
}
// 与步骤 role 相符的 operator；找不到就用激活档案的。与服务端
// harness_roles.resolve() 同一套规则。
function operatorFor(role) {
  const roles = STATE.roles;
  if (!roles || !roles.profiles) return "";
  const match = roles.profiles.find(p => p.role === role && p.operator);
  if (match) return match.operator;
  const active = roles.profiles.find(p => p.id === roles.active_profile);
  return (active && active.operator) || "";
}
function noteTemplate() {
  const roles = STATE.roles;
  if (!roles || !roles.profiles) return "";
  const active = roles.profiles.find(p => p.id === roles.active_profile);
  return (active && active.note_template) || "";
}

// 操作者选择器：下拉列出角色档案里的 operator，外加一个「自定义…」。
//
// 不做成纯下拉：外部工具那类 operator 不在档案里，锁死会让人没法记录真实情况。
// 也不做成纯文本框：那正是这轮要消灭的东西——档案维护了有哪些人，界面就该把它
// 用起来，而不是让人凭记忆重打一遍。
const CUSTOM = "custom";
function operatorPicker(value, onset, onsave) {
  const options = operatorOptions();
  const wrap = el("div", { class: "op-picker" });
  const sel = el("select", { class: "cell" });
  // 显示「操作者 · 角色」。不拼档案 label——那本身常常已经含人名，拼出来会是
  // `zhangsan（张三（人工））` 这种嵌套括号。
  options.forEach(o => sel.appendChild(el("option", { value: o.operator,
    text: o.operator + " · " + PROFILE_ROLE_LABEL(o.role) })));
  sel.appendChild(el("option", { value: CUSTOM, text: "自定义…" }));

  const known = options.some(o => o.operator === value);
  const free = el("input", { class: "cell", value: value || "" });
  free.style.display = known || !value ? "none" : "";
  sel.value = known || !value ? (value || (options[0] && options[0].operator) || "")
                              : CUSTOM;

  sel.addEventListener("change", () => {
    if (sel.value === CUSTOM) {
      free.style.display = "";
      free.focus();
      return;                       // 等人真的填了再写回
    }
    free.style.display = "none";
    onset(sel.value);
    onsave();
  });
  free.addEventListener("change", () => { onset(free.value); onsave(); });
  wrap.appendChild(sel);
  wrap.appendChild(free);
  return { node: wrap, value: () => (sel.value === CUSTOM ? free.value : sel.value) };
}

// 档案里去重后的 operator。空 operator（例如「外部工具」档案）不进下拉——
// 一个选了等于没填的选项只会让人误以为已经填过。
function operatorOptions() {
  const profiles = (STATE.roles && STATE.roles.profiles) || [];
  const seen = new Set();
  const out = [];
  profiles.forEach(p => {
    if (!p.operator || seen.has(p.operator)) return;
    seen.add(p.operator);
    out.push({ operator: p.operator, label: p.label, role: p.role });
  });
  return out;
}
const PROFILE_ROLE_LABEL = r => ({ human: "人工", evaluator: "评估",
  external: "外部" })[r] || r || "未标注";

function textCell(value, onset, onsave) {
  const inp = el("input", { class: "cell", value: value || "" });
  inp.addEventListener("change", () => { onset(inp.value); onsave(); });
  return inp;
}

// ---------- 文档预览 ----------
function docLine(path, size) {
  const holder = el("div");
  const link = el("a", { text: path, onclick: () => {
    if (holder.dataset.loaded) { holder.dataset.loaded=""; holder.querySelector(".md")?.remove(); }
    else loadDocInto(path, holder); } });
  const line = el("div", { class: "docline" }, [link]);
  if (size != null) line.appendChild(el("span", { class: "sz", text: fmtSize(size) }));
  const wrap = el("div"); wrap.appendChild(line); wrap.appendChild(holder); return wrap;
}
async function loadDocInto(path, holder) {
  if (holder.dataset.loaded === path) return;
  holder.innerHTML = "";
  holder.appendChild(el("div", { class: "empty", text: "加载中…" }));
  try {
    const res = await fetch("/api/doc?path=" + encodeURIComponent(path));
    const data = await res.json();
    holder.innerHTML = "";
    if (!res.ok) { holder.appendChild(el("div", { class: "blockers", text: data.error || "加载失败" })); return; }
    const md = el("div", { class: "md", html: renderMarkdown(data.content) });
    holder.appendChild(md); holder.dataset.loaded = path;
  } catch (e) { holder.innerHTML = ""; holder.appendChild(el("div", { class: "blockers", text: String(e) })); }
}

// ---------- 能力索引 / 单篇文档 / 单个 change 的证据 ----------
function renderFeatureIndex(box) {
  const fi = STATE.feature_index;
  if (!fi || !fi.features) {
    pageHeader(box, { title: "能力索引" });
    box.appendChild(el("div", { class: "empty", text: "没有 .harness/feature-index.json。" }));
    return;
  }
  pageHeader(box, { title: "能力索引",
    sub: [fi.project, fi.last_updated && ("更新于 " + fi.last_updated), fi.path]
      .filter(Boolean).join("  ·  ") });
  const body = card(box, "能力", fi.features.length + " 项");
  const t = el("table", { class: "grid" });
  t.appendChild(el("tr", {}, ["领域","能力","成熟度","质量"].map(h => el("th", { text: h }))));
  fi.features.forEach(f => {
    t.appendChild(el("tr", {}, [
      el("td", { class:"cid", text: f.domain || "" }),
      el("td", { text: f.title || f.id || "" }),
      el("td", {}, [el("span", { class: "badge " + (f.maturity||""), text: f.maturity || "\u2014" })]),
      el("td", { text: f.quality == null ? "\u2014" : String(f.quality) }),
    ]));
  });
  body.appendChild(t);
}

function renderSystemPage(box) {
  const graphs = STATE.graphs || {};
  pageHeader(box, { title: "系统结构",
    sub: "两张图都由源数据计算：import 关系与 server.py 的 DATA_FLOW 声明" });
  graphSection(box, "脚本模块依赖", graphs.modules, "由 ast 解析 import 派生");
  graphSection(box, "API 数据流向", graphs.data_flow, "由 server.py 的 DATA_FLOW 派生");
}

function renderDocPage(box, view) {
  pageHeader(box, { title: view.title || view.path, sub: view.path });
  const holder = el("div");
  card(box, "正文").appendChild(holder);
  loadDocInto(view.path, holder);
}

// ---------- \u8bc1\u636e\u6d4f\u89c8 ----------
// \u7b5b\u9009\u903b\u8f91\u5355\u72ec\u4e00\u4efd\u3001\u4e0d\u4e0e\u6e32\u67d3\u8026\u5408\uff0c\u8fd9\u6837\u6d4b\u8bd5\u53ef\u4ee5\u76f4\u63a5\u8c03\u7528\u5b83\uff0c\u800c\u4e0d\u5fc5\u6a21\u62df DOM\u3002
const EVIDENCE_DIMS = [
  { key: "kind", label: "\u7c7b\u578b", of: it => it.kind },
  { key: "source", label: "\u6765\u6e90", of: it => it.source },
  { key: "month", label: "\u6708\u4efd", of: it => (it.date || "").slice(0, 7) },
];

function filterEvidence(items, filters) {
  return (items || []).filter(it =>
    EVIDENCE_DIMS.every(dim => {
      const want = filters[dim.key];
      return !want || dim.of(it) === want;
    }));
}
const KIND_LABEL = k => ({
  image: "\u56fe\u7247", "test-result": "\u6d4b\u8bd5\u7ed3\u679c", log: "\u65e5\u5fd7",
  doc: "\u6587\u6863", script: "\u811a\u672c",
})[k] || k;

function evidenceUrl(path) {
  return "/api/evidence-file?path=" + encodeURIComponent(path);
}

function renderEvidencePage(box, changeId) {
  const index = STATE.evidence_index || { items: [] };
  // changeId \u4e3a\u7a7a = \u300c\u5168\u90e8\u8bc1\u636e\u300d\u3002\u6309 source \u8fc7\u6ee4\u800c\u4e0d\u662f\u6309 change \u7684 evidence \u5217\u8868\uff0c
  // \u90a3\u4e2a\u5217\u8868\u53ea\u8986\u76d6\u73b0\u5b58 change\uff0c\u5386\u53f2\u5e73\u94fa\u7684\u90a3\u6279\u4f1a\u6574\u6279\u6d88\u5931\u3002
  const scoped = changeId
    ? index.items.filter(it => it.source === changeId)
    : index.items;

  pageHeader(box, {
    title: changeId ? "\u8bc1\u636e \u00b7 " + changeId : "\u5168\u90e8\u8bc1\u636e",
    sub: changeId ? ".harness/evidence/" + changeId : ".harness/evidence/",
  });

  if (!scoped.length) {
    card(box, "\u6587\u4ef6", "0 \u4efd").appendChild(
      el("div", { class: "empty", text: "\u6682\u65e0\u8bc1\u636e\u6587\u4ef6\u3002" }));
    return;
  }

  const filters = { kind: "", source: "", month: "" };
  const body = card(box, "\u6587\u4ef6", scoped.length + " \u4efd");
  const chipBox = el("div", { class: "chip-rows" });
  const grid = el("div", { class: "ev-grid" });
  const countLine = el("div", { class: "ev-count" });
  body.appendChild(chipBox);
  body.appendChild(countLine);
  body.appendChild(grid);

  function draw() {
    const shown = filterEvidence(scoped, filters);
    countLine.textContent = "\u663e\u793a " + shown.length + " / " + scoped.length + " \u4efd";
    grid.innerHTML = "";
    shown.forEach(it => grid.appendChild(evidenceCard(it)));
    if (!shown.length)
      grid.appendChild(el("div", { class: "empty", text: "\u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u8bc1\u636e\u3002" }));
  }

  EVIDENCE_DIMS.forEach(dim => {
    // \u9009\u9879\u7531\u6570\u636e\u7b97\uff0c\u4e0d\u786c\u7f16\u7801\uff1a\u786c\u7f16\u7801\u7684\u5217\u8868\u5728\u65b0\u589e\u4e00\u7c7b\u8bc1\u636e\u540e\u4e0d\u4f1a\u81ea\u5df1\u957f\u51fa\u6765\uff0c
    // \u90a3\u7c7b\u8bc1\u636e\u5c31\u4f1a\u540c\u65f6\u4e0d\u5728\u4efb\u4f55\u9009\u9879\u91cc\u3001\u4e5f\u4e0d\u5728\u4efb\u4f55\u7b5b\u9009\u7ed3\u679c\u91cc\u3002
    const values = [...new Set(scoped.map(dim.of))].filter(Boolean).sort();
    if (values.length < 2) return;   // \u53ea\u6709\u4e00\u4e2a\u53d6\u503c\u65f6\u7b5b\u9009\u6ca1\u6709\u610f\u4e49
    const row = el("div", { class: "chip-row" }, [
      el("span", { class: "chip-label", text: dim.label })]);
    const chips = [];
    function select(value) {
      filters[dim.key] = value;
      chips.forEach(c => c.classList.toggle("on", c.dataset.value === value));
      draw();
    }
    [["", "\u5168\u90e8"], ...values.map(v => [v, dim.key === "kind" ? KIND_LABEL(v) : v])]
      .forEach(([value, label]) => {
        const n = scoped.filter(it => !value || dim.of(it) === value).length;
        const chip = el("button", {
          class: "chip" + (value === "" ? " on" : ""),
          text: label + " " + n,
          onclick: () => select(value),
        });
        chip.dataset.value = value;
        chips.push(chip);
        row.appendChild(chip);
      });
    chipBox.appendChild(row);
  });

  draw();
}

function evidenceCard(it) {
  const cell = el("div", { class: "ev-cell" });
  if (it.kind === "image") {
    // \u53ea\u7ecf <img src> \u8f7d\u5165\uff0c\u7edd\u4e0d innerHTML\uff1aSVG \u91cc\u53ef\u4ee5\u5199 <script>\uff0c\u4f5c\u4e3a\u56fe\u7247
    // \u8f7d\u5165\u65f6\u6d4f\u89c8\u5668\u4e0d\u6267\u884c\u5b83\uff0c\u5185\u8054\u8fdb DOM \u5219\u4f1a\u6267\u884c\u3002
    const img = el("img", { class: "ev-thumb", src: evidenceUrl(it.path),
                            alt: it.path, loading: "lazy" });
    const link = el("a", { class: "ev-link", href: evidenceUrl(it.path),
                           target: "_blank", rel: "noopener" });
    link.appendChild(img);
    cell.appendChild(link);
  } else {
    const holder = el("div");
    cell.appendChild(el("button", {
      class: "chip ev-open", text: "\u9884\u89c8 " + KIND_LABEL(it.kind),
      onclick: () => {
        if (holder.dataset.loaded) { holder.dataset.loaded = ""; holder.innerHTML = ""; }
        else loadDocInto(it.path, holder);
      }}));
    cell.appendChild(holder);
  }
  cell.appendChild(el("div", { class: "ev-name", text: it.path.split("/").pop(),
                               title: it.path }));
  const meta = [it.date, fmtSize(it.size)];
  cell.appendChild(el("div", { class: "ev-meta", text: meta.join(" \u00b7 ") }));
  if (it.referenced_by && it.referenced_by.length)
    cell.appendChild(el("div", { class: "ev-meta",
      text: "\u652f\u6491 " + it.referenced_by.join("\u3001") }));
  return cell;
}

// ---------- 轻量 markdown 渲染 ----------
function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function inlineMd(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, (m,a)=>"<code>"+a+"</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function renderMarkdown(text) {
  const lines = text.replace(/\r\n/g,"\n").split("\n");
  let html = "", i = 0, inCode = false, codeBuf = [];
  let listBuf = [], tableBuf = [];
  function flushList(){ if(listBuf.length){ html += "<ul>" + listBuf.map(x=>"<li>"+x+"</li>").join("") + "</ul>"; listBuf=[]; } }
  function flushTable(){
    if(!tableBuf.length) return;
    const parse = r => r.replace(/^\|/,"").replace(/\|\s*$/,"").split("|").map(c=>c.trim());
    const isSep = r => /^[\s|:-]+$/.test(r) && r.includes("-");
    const body = tableBuf.filter(r => !isSep(r));
    if(body.length){
      let t = "<table>";
      body.forEach((r, idx) => {
        const cells = parse(r);
        const tag = idx===0 ? "th" : "td";
        t += "<tr>" + cells.map(c => "<"+tag+">"+ renderCell(c) +"</"+tag+">").join("") + "</tr>";
      });
      t += "</table>"; html += t;
    }
    tableBuf = [];
  }
  function renderCell(c){
    c = c.replace(/^\[x\]$/i, '<span class="cbx">✔</span>').replace(/^\[ \]$/, '☐');
    return inlineMd(c);
  }
  for (; i < lines.length; i++) {
    let line = lines[i];
    if (/^```/.test(line)) {
      if (inCode) { html += "<pre><code>" + esc(codeBuf.join("\n")) + "</code></pre>"; codeBuf=[]; inCode=false; }
      else { flushList(); flushTable(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) { flushList(); tableBuf.push(line.trim()); continue; }
    else flushTable();
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flushList(); html += "<h"+h[1].length+">"+inlineMd(h[2])+"</h"+h[1].length+">"; continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { let c = li[1].replace(/^\[x\]\s*/i,'<span class="cbx">✔</span> ').replace(/^\[ \]\s*/,'☐ '); listBuf.push(inlineMd(c)); continue; }
    flushList();
    if (line.trim() === "") { continue; }
    html += "<p>" + inlineMd(line) + "</p>";
  }
  if (inCode) html += "<pre><code>" + esc(codeBuf.join("\n")) + "</code></pre>";
  flushList(); flushTable();
  return html;
}

document.getElementById("refresh").addEventListener("click", load);
document.getElementById("sbToggle").addEventListener("click", () =>
  document.getElementById("app").classList.toggle("nav-open"));
document.getElementById("scrim").addEventListener("click", () =>
  document.getElementById("app").classList.remove("nav-open"));
load().catch(e => toast("加载失败: " + e, "err"));
