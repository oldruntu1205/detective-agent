/* 粒子背景 · 纯 Canvas 2D · 零依赖
 *
 * 移植自 H:\MyWork\前卫前端UI\components\ParticleCanvas.tsx，
 * 参数原样取自 lib/design-tokens.ts 的 CANVAS_2D + CANVAS_2D_VARIANTS.particleCanvas：
 *   速度跨度 0.45 / 半径 0.8~2.0 / 透明度 0.2~0.6 /
 *   粒子连线阈值 75 / 光标磁吸阈值 95 / 连线 alpha 0.18 / 光标连线 alpha 0.35
 *
 * 与原始组件只有三点差异，都是为了从「卡片背景」改当「页面背景」：
 *   1. 画布 fixed 铺满视口，不依赖父容器尺寸，鼠标坐标就是视口坐标；
 *   2. 颜色与亮度从 CSS 变量读（--pt-dot / --pt-link / --pt-mouse / --pt-boost），
 *      日间夜间切换时只重读颜色，不重建粒子池，粒子位置保持连续；
 *   3. 尊重 prefers-reduced-motion：不跑动画，只静态铺一帧。
 *
 * 粒子数不是原素材的 40：40 是「卡片」变体的取值，铺满一屏只剩零星几点。
 * 原作者自己给整页 demo 抬到了 400（见 ParticleCanvasProps 注释）。
 * 这里按视口面积自适应，60~200，1400x900 落在 200 上限，手机上退回 60：
 * 密度跟面积走，换显示器不用重调参，同时把 O(n²) 的连线判定压在 2 万次/帧以内。
 */
(function (global) {
  "use strict";

  var CFG = {
    countMin: 60,
    countMax: 200,
    areaPerParticle: 5500,
    velocitySpan: 0.45,
    radiusScale: 1.2,
    radiusMin: 0.8,
    alphaSpan: 0.4,
    alphaMin: 0.2,
    connectDist: 75,
    mouseConnectDist: 95,
    mouseLineWidth: 1,
    linkAlphaScale: 0.18,
    linkLineWidth: 0.8,
    mouseLinkAlphaScale: 0.35
  };

  var canvas = null;
  var ctx = null;
  var raf = 0;
  var running = false;
  var width = 0;
  var height = 0;
  var dpr = 1;
  var reduceMotion = false;
  var particles = [];
  var mouse = { x: null, y: null };
  var tone = { dot: "99, 102, 241", link: "79, 70, 229", mouse: "124, 58, 237", boost: 1.45 };
  var resizeTimer = 0;

  /* 从 :root / [data-theme] 上读当前主题的粒子配色 */
  function readTone() {
    var cs = global.getComputedStyle(document.documentElement);
    function pick(name, fallback) {
      var v = cs.getPropertyValue(name);
      v = v ? v.trim() : "";
      return v || fallback;
    }
    tone.dot = pick("--pt-dot", tone.dot);
    tone.link = pick("--pt-link", tone.link);
    tone.mouse = pick("--pt-mouse", tone.mouse);
    var b = parseFloat(pick("--pt-boost", String(tone.boost)));
    tone.boost = isFinite(b) && b > 0 ? b : 1;
  }

  function countFor(area) {
    var n = Math.round(area / CFG.areaPerParticle);
    return Math.max(CFG.countMin, Math.min(CFG.countMax, n));
  }

  function seed() {
    var target = countFor(width * height);
    particles.length = 0;
    for (var i = 0; i < target; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * CFG.velocitySpan,
        vy: (Math.random() - 0.5) * CFG.velocitySpan,
        r: Math.random() * CFG.radiusScale + CFG.radiusMin,
        a: Math.random() * CFG.alphaSpan + CFG.alphaMin
      });
    }
  }

  function resize() {
    if (!canvas || !ctx) return;
    /* 参考实现不封顶；这里封到 2，避免 4K + 高 DPR 屏上把填充率吃满 */
    dpr = Math.min(global.devicePixelRatio || 1, 2);
    width = global.innerWidth;
    height = global.innerHeight;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";

    /* 用 setTransform 而不是 scale：重复 resize 时不会把缩放累乘上去 */
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
  }

  function paint(step) {
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];

      if (step) {
        p.x += p.vx;
        p.y += p.vy;
        /* 边界环回：从右边出去就从左边进来，不留空白 */
        if (p.x < 0) p.x += width;
        else if (p.x > width) p.x -= width;
        if (p.y < 0) p.y += height;
        else if (p.y > height) p.y -= height;
      }

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(" + tone.dot + ", " + p.a + ")";
      ctx.fill();

      /* 粒子之间的弱光纤网络 */
      for (var j = i + 1; j < particles.length; j++) {
        var q = particles[j];
        var dx = p.x - q.x;
        var dy = p.y - q.y;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < CFG.connectDist) {
          var alpha = (1 - d / CFG.connectDist) * CFG.linkAlphaScale * tone.boost;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.strokeStyle = "rgba(" + tone.link + ", " + alpha.toFixed(3) + ")";
          ctx.lineWidth = CFG.linkLineWidth;
          ctx.stroke();
        }
      }

      /* 光标磁吸连线 */
      if (mouse.x !== null && mouse.y !== null) {
        var mx = p.x - mouse.x;
        var my = p.y - mouse.y;
        var md = Math.sqrt(mx * mx + my * my);
        if (md < CFG.mouseConnectDist) {
          var ma = (1 - md / CFG.mouseConnectDist) * CFG.mouseLinkAlphaScale * tone.boost;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.strokeStyle = "rgba(" + tone.mouse + ", " + ma.toFixed(3) + ")";
          ctx.lineWidth = CFG.mouseLineWidth;
          ctx.stroke();
        }
      }
    }
  }

  function loop() {
    paint(true);
    raf = global.requestAnimationFrame(loop);
  }

  function start() {
    if (!canvas || !ctx) return;
    if (reduceMotion) {
      paint(false);
      return;
    }
    if (running) return;
    running = true;
    raf = global.requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    if (raf) {
      global.cancelAnimationFrame(raf);
      raf = 0;
    }
  }

  function setTheme() {
    readTone();
    /* 动画没在跑（reduced-motion 或页面隐藏）时补一帧，否则颜色要等下一帧才更新 */
    if (!running) paint(false);
  }

  function init(el) {
    canvas = el || document.getElementById("particles");
    if (!canvas) return false;
    ctx = canvas.getContext("2d");
    if (!ctx) return false;

    reduceMotion = !!(global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches);

    readTone();
    resize();
    start();

    global.addEventListener("resize", function () {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        resize();
        if (!running) paint(false);
      }, 150);
    });

    global.addEventListener("mousemove", function (e) {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    }, { passive: true });

    /* 鼠标离开窗口后别再留着一束线挂在边上 */
    document.addEventListener("mouseleave", function () {
      mouse.x = null;
      mouse.y = null;
    });
    global.addEventListener("blur", function () {
      mouse.x = null;
      mouse.y = null;
    });

    /* 切到后台就停，回来再起——后台标签页不该继续烧 CPU */
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else start();
    });

    return true;
  }

  global.Particles = { init: init, setTheme: setTheme, start: start, stop: stop };
})(window);
