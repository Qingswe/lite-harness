// 分层有向图的 SVG 渲染器。
//
// 手写而不是引 mermaid / d3：README 把「零依赖、无 CDN、可离线」列为承重属性，
// 而本仓库只需要分层 DAG 一种图形。几百 KB 的图库换不来别的能力。
//
// 输入：{nodes:[{id, kind, rank, label, detail, status}], edges:[{from,to,kind}]}
// 输出：一个 <svg>。节点按 rank 分列、同列纵向排，直角折线连接，单向箭头。
(function (global) {
  "use strict";

  const NODE_W = 256;
  const NODE_H = 72;
  const COL_GAP = 96;
  const ROW_GAP = 16;
  const PAD = 16;
  const TEXT_X = 12;
  const LABEL_Y = 26;        // 标签基线
  const DETAIL_Y = 46;       // 第一行说明的基线
  const DETAIL_LEAD = 15;    // 说明的行距
  const NS = "http://www.w3.org/2000/svg";
  // 以拉丁字符宽为 1 个单位。字号由 theme.css 的阶梯决定：标签走 --fs-2（14px
  // 等宽 ≈ 8.4px/字），说明走 --fs-1（12px 比例字体 ≈ 6.6px/字）。这两个系数
  // 跟着 CSS 走——改了 .g-label / .g-detail 的字号就要回来改这里，否则文字会
  // 画到框外面去。
  const LABEL_BUDGET = Math.floor((NODE_W - TEXT_X * 2) / 8.4);
  const DETAIL_BUDGET = Math.floor((NODE_W - TEXT_X * 2) / 6.6);

  function svgEl(tag, attrs, children) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) {
      if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(c => c && e.appendChild(c));
    return e;
  }

  // 状态到 CSS class：颜色一律由 theme.css 的 token 决定，这里不写色值。
  function nodeClass(node) {
    const bits = ["g-node", "g-" + (node.kind || "node")];
    if (node.status) bits.push("g-s-" + node.status);
    if (node.role) bits.push("g-role-" + node.role);
    return bits.join(" ");
  }

  // 按 rank 分列；同一列内保持输入顺序，让图与文字摘要的编号顺序一致。
  function layout(nodes) {
    const ranks = new Map();
    nodes.forEach(n => {
      const r = n.rank || 0;
      if (!ranks.has(r)) ranks.set(r, []);
      ranks.get(r).push(n);
    });
    const cols = [...ranks.keys()].sort((a, b) => a - b);
    const tallest = Math.max(...cols.map(r => ranks.get(r).length), 1);
    const height = PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP;
    const placed = new Map();
    cols.forEach((r, ci) => {
      const list = ranks.get(r);
      const colH = list.length * NODE_H + (list.length - 1) * ROW_GAP;
      const top = (height - colH) / 2;
      list.forEach((n, ri) => {
        placed.set(n.id, {
          node: n,
          x: PAD + ci * (NODE_W + COL_GAP),
          y: top + ri * (NODE_H + ROW_GAP),
        });
      });
    });
    return {
      placed,
      width: PAD * 2 + cols.length * NODE_W + (cols.length - 1) * COL_GAP,
      height,
    };
  }

  // 直角折线：从起点右边出发，在两列中间折一次，进到终点左边。
  function orthPath(a, b) {
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
    const x2 = b.x, y2 = b.y + NODE_H / 2;
    if (Math.abs(y1 - y2) < 1) return "M" + x1 + "," + y1 + " L" + x2 + "," + y2;
    const mid = x1 + (x2 - x1) / 2;
    return "M" + x1 + "," + y1 + " L" + mid + "," + y1 +
           " L" + mid + "," + y2 + " L" + x2 + "," + y2;
  }

  // SVG 的 <text> 不会自己换行也不会自己截断，长标识符会直接画到框外面去。
  // change id 和脚本名经常有 40 多个字符，所以按宽度切，而不是按字符数：中日韩
  // 字符大约是拉丁字符的两倍宽，按字符数切会让中文说明提前断掉、英文 id 溢出。
  function units(ch) {
    return /[⺀-鿿豈-﫿＀-｠]/.test(ch) ? 2 : 1;
  }

  function clip(text, budget) {
    let used = 0, out = "";
    for (const ch of String(text || "")) {
      const w = units(ch);
      if (used + w > budget) return out + "…";
      used += w;
      out += ch;
    }
    return out;
  }

  function wrap(text, budget, maxLines) {
    const lines = [];
    let used = 0, line = "";
    for (const ch of String(text || "")) {
      const w = units(ch);
      if (used + w > budget) {
        lines.push(line);
        if (lines.length >= maxLines) return lines;
        line = ""; used = 0;
      }
      line += ch; used += w;
    }
    if (line) lines.push(line);
    return lines;
  }

  /**
   * 渲染一张图。
   * @param {object} graph  {nodes, edges}
   * @param {object} opts   {title} 无障碍标题，必填——图必须能被读出来。
   */
  function render(graph, opts) {
    const options = opts || {};
    const nodes = (graph && graph.nodes) || [];
    if (!nodes.length) return null;
    const { placed, width, height } = layout(nodes);

    const marker = svgEl("marker", {
      id: "g-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
      markerWidth: "6", markerHeight: "6", orient: "auto-start-reverse",
    }, [svgEl("path", { d: "M0,0 L10,5 L0,10 z", class: "g-arrowhead" })]);

    const svg = svgEl("svg", {
      class: "graph", viewBox: "0 0 " + width + " " + height,
      width: "100%", height: height, role: "img",
      "aria-label": options.title || "关系图",
      preserveAspectRatio: "xMinYMin meet",
    }, [svgEl("title", {}, [document.createTextNode(options.title || "关系图")]),
        svgEl("defs", {}, [marker])]);

    ((graph && graph.edges) || []).forEach(edge => {
      const a = placed.get(edge.from), b = placed.get(edge.to);
      if (!a || !b) return;
      // 只有 marker-end：单向箭头，方向不产生歧义。
      svg.appendChild(svgEl("path", {
        d: orthPath(a, b), class: "g-edge g-edge-" + (edge.kind || "plain"),
        "marker-end": "url(#g-arrow)", fill: "none",
      }));
    });

    placed.forEach(pos => {
      const n = pos.node;
      const g = svgEl("g", { class: nodeClass(n), transform:
        "translate(" + pos.x + "," + pos.y + ")" });
      g.appendChild(svgEl("rect", {
        width: NODE_W, height: NODE_H, rx: 8, class: "g-box" }));
      // 标签加粗等宽，说明小一档；两者的字宽不同，所以预算也不同。
      g.appendChild(svgEl("text", { x: TEXT_X, y: LABEL_Y, class: "g-label" },
        [document.createTextNode(clip(n.label || n.id, LABEL_BUDGET))]));
      wrap(n.detail, DETAIL_BUDGET, 2).forEach((line, i) => {
        g.appendChild(svgEl("text", {
          x: TEXT_X, y: DETAIL_Y + i * DETAIL_LEAD, class: "g-detail" },
          [document.createTextNode(line)]));
      });
      // 悬停能读到未截断的全文。
      g.appendChild(svgEl("title", {}, [document.createTextNode(
        (n.label || n.id) + (n.detail ? "\n" + n.detail : ""))]));
      svg.appendChild(g);
    });

    return svg;
  }

  global.HarnessGraph = { render, layout };
})(window);
