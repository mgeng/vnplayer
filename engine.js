/* novela VN Player — 軽量自作Webエンジン
 *
 * SCHEMA.md (novela-game/1) のバンドルを読んで再生する。
 * 既定では ./bundle/ から script.json / meta.json / cast.json を読む。
 * ?bundle=path/to/dir でバンドルの場所を差し替えられる。
 *
 * 画像は assets/ から解決し、欠損時はプレースホルダで継続する
 * （SCHEMA 不変条件3：画像欠損は致命ではない）。
 *
 * BGM は scene.bgm（曲ID）を元に assets/bgm/<id>.mp3 から解決する。
 * バンドルではなくエンジン共有の assets/bgm/ を参照する。
 * シーン遷移時に曲が変わる場合はクロスフェード。null/未指定は現在の曲を維持。
 */
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  // スタンドアロン配布（file://）では bundle.js が window.NOVELA_BUNDLE を埋め込む。
  // あればそれを使い fetch しない。無ければ従来どおり bundle/ から fetch（dev: http.server）。
  const INLINE = (typeof window !== "undefined" && window.NOVELA_BUNDLE) || null;
  const BUNDLE = INLINE ? "." : (params.get("bundle") || "bundle").replace(/\/$/, "");
  const ASSETS = `${BUNDLE}/assets`;
  // BGMはバンドルではなくエンジン共有ディレクトリから解決する（dist でも assets/bgm/ に同梱）
  const BGM_DIR = "assets/bgm";

  const el = (id) => document.getElementById(id);
  const dom = {
    stage: el("stage"),
    bg: el("bg"), sprites: el("sprites"), cg: el("cg"),
    title: el("title"), cover: el("title-cover"),
    titleName: el("title-name"), titleSub: el("title-sub"), titleAuthor: el("title-author"),
    startBtn: el("start-btn"),
    choices: el("choices"),
    textbox: el("textbox"), speaker: el("speaker"), text: el("text"),
    hudTitle: el("hud-title"), hudScene: el("hud-scene"),
    titlecard: el("titlecard"), titlecardText: el("titlecard-text"),
    faceWindow: el("face-window"), faceImg: el("face-img"), facePh: el("face-placeholder"),
  };

  const state = {
    script: null, meta: null, cast: null,
    castByName: {},
    sceneIndex: 0, lineIndex: 0,
    currentBg: null,
    currentCg: null,    // 現在表示中のイベントCGのID（null=非表示）
    currentSprite: null,// 現在表示中の立ち絵ID（null=非表示）。戻る機能の状態復元に使う
    currentFace: null,  // 現在の顔ウィンドウID
    currentBgm: null,   // 現在再生中の曲ID
    bgmMuted: false,    // ミュート状態
    cardActive: false,  // 転換カード表示中はテキスト送りを止める
    cgHold: false,      // 全画面CGを「画だけ」表示してシナリオを止めている状態
    cgHoldLine: null,   // 保留中のCG行（クリック後にこの行の本文を表示する）
    history: [],        // 表示済みビートのスナップショット列（上キーで1つ戻る）
  };

  // BGM: 2枚の<audio>タグでクロスフェード実装
  const bgmTracks = [
    document.createElement("audio"),
    document.createElement("audio"),
  ];
  bgmTracks.forEach((a) => {
    a.loop = true;
    a.volume = 0;
    document.body.appendChild(a);
  });
  let bgmActive = 0; // 現在メインのトラックインデックス（0 or 1）
  const FADE_DURATION = 800; // クロスフェード時間（ms）

  function bgmFadeTo(trackIdx, targetVol, durationMs, onDone) {
    const track = bgmTracks[trackIdx];
    const startVol = track.volume;
    const startTime = performance.now();
    function step(now) {
      const t = Math.min((now - startTime) / durationMs, 1);
      // 浮動小数で僅かに範囲外へ出ると setter が例外を投げるので [0,1] にクランプ
      const v = startVol + (targetVol - startVol) * t;
      track.volume = v < 0 ? 0 : v > 1 ? 1 : v;
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        track.volume = targetVol;
        if (onDone) onDone();
      }
    }
    requestAnimationFrame(step);
  }

  // BGM再生。bgmId が null/未指定なら現在を維持。欠損時はエラーで止めない。
  function playBgm(bgmId) {
    if (!bgmId || bgmId === state.currentBgm) return; // null=維持、同曲=途切れさせない
    const newSrc = `${BGM_DIR}/${bgmId}.mp3`;
    const next = 1 - bgmActive;
    const curr = bgmActive;

    bgmTracks[next].src = newSrc;
    bgmTracks[next].currentTime = 0;
    bgmTracks[next].volume = 0;

    // 音源欠損時も catch で飲み込んでゲームは続行する
    bgmTracks[next].play().then(() => {
      if (!state.bgmMuted) {
        bgmFadeTo(next, 1, FADE_DURATION, null);
      }
      bgmFadeTo(curr, 0, FADE_DURATION, () => {
        bgmTracks[curr].pause();
        bgmTracks[curr].src = "";
      });
      bgmActive = next;
      state.currentBgm = bgmId;
    }).catch(() => {
      // 音源欠損またはポリシーによる再生失敗 → 無視して継続
    });
  }

  function toggleMute() {
    state.bgmMuted = !state.bgmMuted;
    bgmTracks.forEach((a) => { a.muted = state.bgmMuted; });
    const btn = el("mute-btn");
    if (btn) btn.textContent = state.bgmMuted ? "🔇" : "🔊";
  }

  async function loadJSON(name) {
    const r = await fetch(`${BUNDLE}/${name}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: ${r.status}`);
    return r.json();
  }

  // 画像URLを試し、無ければ null（プレースホルダに落とす）
  function tryImage(url) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(url);
      img.onerror = () => resolve(null);
      img.src = url;
    });
  }

  async function setBackground(bgId) {
    if (bgId === state.currentBg) return;
    state.currentBg = bgId;
    if (!bgId) { dom.bg.style.backgroundImage = ""; return; }
    const url = await tryImage(`${ASSETS}/bg_${bgId}.png`);
    dom.bg.style.backgroundImage = url ? `url("${url}")` : "";
  }

  // 顔ウィンドウ更新。spriteId が null/未指定のときは現在の表示を維持する（立ち絵と同思想）。
  // spriteId が文字列のとき assets/face_<spriteId>.png を試し、欠損時はプレースホルダ表示。
  async function updateFaceWindow(spriteId) {
    if (!spriteId) return; // null/未指定 → 維持
    state.currentFace = spriteId;
    const url = await tryImage(`${ASSETS}/face_${spriteId}.png`);
    if (url) {
      dom.faceImg.src = url;
      dom.facePh.classList.remove("active");
      dom.faceImg.style.display = "block";
    } else {
      dom.faceImg.src = "";
      dom.faceImg.style.display = "none";
      dom.facePh.classList.add("active");
    }
  }

  async function showSprite(spriteId) {
    state.currentSprite = spriteId || null;
    dom.sprites.innerHTML = "";
    if (!spriteId) return;
    const url = await tryImage(`${ASSETS}/char_${spriteId}.png`);
    if (url) {
      const img = document.createElement("img");
      img.className = "sprite";
      img.src = url;
      dom.sprites.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "sprite-placeholder";
      dom.sprites.appendChild(ph);
    }
  }

  // イベントCG（1枚絵）更新。スクリプト契約：
  //   cgId が null/未指定 → 現在の状態を維持（何もしない）
  //   cgId が非空文字列   → assets/cg_<id>.png を全画面オーバーレイ表示（立ち絵・顔窓は隠れる）
  //   cgId が ""          → CGを消し、背景＋立ち絵の表示へ戻す
  // 画像欠損時は tryImage が null を返すので、壊れた画像を出さずCGを張らない（背景/立ち絵を維持）。
  async function showCg(cgId) {
    if (cgId == null) return; // null/未指定 → 維持
    if (cgId === "") {
      // CGクリア：active を外すと opacity が 0 へフェードアウトする。
      // src はここでは消さない（消すとフェード中に絵が抜けて瞬間的に白くなるため）。
      // visibility はフェード完了後に CSS 側の遅延で hidden になる。
      state.currentCg = null;
      dom.cg.classList.remove("active");
      dom.stage.classList.remove("cg-active");
      return;
    }
    if (cgId === state.currentCg) return; // 同じCGなら張り直さない
    const url = await tryImage(`${ASSETS}/cg_${cgId}.png`);
    if (url) {
      state.currentCg = cgId;
      dom.cg.src = url;
      dom.cg.classList.add("active");
      dom.stage.classList.add("cg-active");
    }
    // 欠損時は何もしない（背景・立ち絵のまま継続）
  }

  function currentScene() { return state.script.scenes[state.sceneIndex]; }

  function sceneById(id) {
    return state.script.scenes.findIndex((s) => s.id === id);
  }

  // 次の scene へ。next 指定 > 配列順。末尾なら終了。
  function gotoSceneId(id) {
    const idx = sceneById(id);
    if (idx < 0) { console.warn("goto 先が無い:", id); return endGame(); }
    state.sceneIndex = idx;
    state.lineIndex = 0;
    renderScene();
  }

  // エピソード転換カード。話が変わるとき中央にタイトルを出す。
  // クリック/キーで早送り可、放置でも自動で進む。
  function showTitleCard(text) {
    return new Promise((resolve) => {
      state.cardActive = true;
      // 転換カード表示中は顔窓を隠す
      dom.faceWindow.classList.add("hidden");
      dom.titlecardText.textContent = text;
      dom.titlecard.classList.remove("hidden");
      void dom.titlecard.offsetWidth; // reflow してからフェードイン
      dom.titlecard.classList.add("show");
      let done = false;
      const finish = () => {
        if (done) return; done = true;
        clearTimeout(timer);
        dom.titlecard.onclick = null;
        dom.titlecard.classList.remove("show");
        setTimeout(() => {
          dom.titlecard.classList.add("hidden");
          state.cardActive = false;
          // 転換カード終了後は顔窓を再表示（本編中なのでプレースホルダのままでも可）
          dom.faceWindow.classList.remove("hidden");
          resolve();
        }, 600); // フェードアウト分待つ
      };
      const timer = setTimeout(finish, 2200); // 表示ホールド
      dom.titlecard.onclick = (e) => { e.stopPropagation(); finish(); };
    });
  }

  async function renderScene() {
    const sc = currentScene();
    dom.hudScene.textContent = sc.heading || sc.id;
    await setBackground(sc.bg);
    // scene.bgm が指定されている場合のみ切り替え。null/未指定なら現在の曲を維持。
    if (sc.bgm) playBgm(sc.bgm);
    // scene.chapter があれば転換カードを挟む（背景・BGMはカードの裏で先に切替済み）
    if (sc.chapter) await showTitleCard(sc.chapter);
    await showSprite(null);
    // シーン遷移ごとにイベントCGは自動クリア（各シーンはCGなしで開始）
    state.cgHold = false; state.cgHoldLine = null;
    await showCg("");
    nextLine();
  }

  function nextLine() {
    const sc = currentScene();

    // 全画面CGを「画だけ」表示して止めている状態：クリックされたらCGを消し、
    // 保留していた行の本文を通常のテキスト窓で表示する（画→クリック→本文）。
    if (state.cgHold) {
      const held = state.cgHoldLine;
      state.cgHold = false;
      state.cgHoldLine = null;
      showCg(""); // CGを消す → cg-active が外れ textbox/立ち絵が戻る
      renderTextLine(held);
      return;
    }

    if (state.lineIndex >= sc.lines.length) {
      // scene 終端
      if (sc.next) return gotoSceneId(sc.next);
      if (state.sceneIndex + 1 < state.script.scenes.length) {
        state.sceneIndex++; state.lineIndex = 0;
        return renderScene();
      }
      return endGame();
    }
    const line = sc.lines[state.lineIndex];
    state.lineIndex++;

    if (line.type === "choice") {
      pushHistory("choice", line);
      return showChoices(line);
    }

    // 非空CGを持つ行：まず全画面で「画だけ」を出し、シナリオは止める。
    // 本文（この行の text）はクリックでCGを消した後に表示する。
    if (Object.prototype.hasOwnProperty.call(line, "cg") && line.cg) {
      showCg(line.cg); // cg-active CSS で textbox/顔窓が隠れる＝画だけ
      state.cgHold = true;
      state.cgHoldLine = line;
      pushHistory("cghold", line);
      return;
    }

    renderTextLine(line);
  }

  // dialogue / narration 行を通常のテキスト窓で表示する。
  function renderTextLine(line) {
    const isDialogue = line.type === "dialogue" || line.speaker;
    dom.speaker.textContent = isDialogue && line.speaker && line.speaker !== "?" ? line.speaker : "";
    // 立ち絵は sprite が明示されたときだけ差し替える。
    // null/未指定なら維持（一人称の語り手のセリフや地の文でヒロインを消さない）。
    if (line.sprite) showSprite(line.sprite);
    // 顔ウィンドウ：sprite が明示されたときだけ更新（null/未指定なら現在の表情を維持）。
    updateFaceWindow(line.sprite || null);
    // イベントCG：cg="" のクリアのみここで反映する。
    // 非空CGは nextLine 側の「画だけ」ビート専用。ここで再表示してはいけない
    // （held 行を本文表示する際に再 showCg すると cg-active がテキスト窓を隠し直し、
    //  本文が一瞬見えてから画に戻る＝固まる・ちらつく不安定の主因）。
    if (Object.prototype.hasOwnProperty.call(line, "cg") && line.cg === "") showCg("");
    dom.text.textContent = line.text || "";
    pushHistory("text", line);
  }

  function showChoices(line) {
    dom.choices.innerHTML = "";
    if (line.prompt) {
      const p = document.createElement("div");
      p.id = "choice-prompt";
      p.style.cssText = "color:var(--ink);font-size:20px;margin-bottom:8px;text-shadow:var(--shadow)";
      p.textContent = line.prompt;
      dom.choices.appendChild(p);
    }
    (line.options || []).forEach((opt) => {
      const b = document.createElement("button");
      b.className = "choice-btn";
      b.textContent = opt.text;
      b.onclick = (e) => {
        e.stopPropagation();
        dom.choices.classList.add("hidden");
        gotoSceneId(opt.goto);
      };
      dom.choices.appendChild(b);
    });
    dom.choices.classList.remove("hidden");
  }

  function endGame() {
    dom.textbox.classList.add("hidden");
    dom.speaker.textContent = "";
    dom.sprites.innerHTML = "";
    state.cgHold = false; state.cgHoldLine = null;
    // イベントCGもクリア（タイトルに戻るので消す）
    showCg("");
    // 顔窓リセット（タイトル画面に戻るので非表示）
    dom.faceWindow.classList.add("hidden");
    dom.faceImg.src = "";
    dom.faceImg.style.display = "none";
    dom.facePh.classList.remove("active");
    dom.title.classList.remove("hidden");
    state.sceneIndex = 0; state.lineIndex = 0;
    state.currentBg = "__reset__";
    state.history = [];
  }

  function startGame() {
    dom.title.classList.add("hidden");
    dom.textbox.classList.remove("hidden");
    // 本編開始時に顔窓を表示（最初はプレースホルダ状態）
    dom.facePh.classList.add("active");
    dom.faceWindow.classList.remove("hidden");
    // 「はじめる」クリックがユーザージェスチャになるので BGM 解禁フラグを立てる
    // 最初のシーンの bgm は renderScene → playBgm で鳴り始める
    state.bgmReady = true;
    state.history = [];
    const startId = state.script.start || (state.script.scenes[0] && state.script.scenes[0].id);
    gotoSceneId(startId);
  }

  function buildCastIndex() {
    state.castByName = {};
    ((state.cast && state.cast.characters) || []).forEach((c) => {
      state.castByName[c.name] = c;
    });
  }

  function advance() {
    if (state.cardActive) return;                          // 転換カード表示中は無視
    if (!dom.choices.classList.contains("hidden")) return; // 選択肢表示中は無視
    if (dom.title.classList.contains("hidden")) nextLine();
  }

  // ── 戻る機能 ───────────────────────────────────────────────
  // 表示する各ビート（本文行 / 全画面CGの「画だけ」 / 選択肢）の時点で、
  // 画面の見た目と進行位置のスナップショットを history に積む。
  // 上キーで pop して直前のスナップショットを復元する＝1ビート戻る。

  function pushHistory(kind, line) {
    state.history.push({
      kind, line,
      sceneIndex: state.sceneIndex, lineIndex: state.lineIndex,
      cgHold: state.cgHold, cgHoldLine: state.cgHoldLine,
      bg: state.currentBg, sprite: state.currentSprite, face: state.currentFace,
      bgm: state.currentBgm,
      speaker: dom.speaker.textContent, text: dom.text.textContent,
    });
  }

  // 顔ウィンドウを指定IDに直接合わせる（復元用。null ならクリア）。
  async function applyFaceDirect(faceId) {
    state.currentFace = faceId;
    if (!faceId) {
      dom.faceImg.src = ""; dom.faceImg.style.display = "none";
      dom.facePh.classList.add("active");
      return;
    }
    const url = await tryImage(`${ASSETS}/face_${faceId}.png`);
    if (url) {
      dom.faceImg.src = url; dom.facePh.classList.remove("active");
      dom.faceImg.style.display = "block";
    } else {
      dom.faceImg.src = ""; dom.faceImg.style.display = "none";
      dom.facePh.classList.add("active");
    }
  }

  // スナップショットの見た目と位置を復元する（history には積み直さない）。
  function restoreSnapshot(snap) {
    dom.choices.classList.add("hidden");
    state.sceneIndex = snap.sceneIndex;
    state.lineIndex = snap.lineIndex;
    state.cgHold = snap.cgHold;
    state.cgHoldLine = snap.cgHoldLine;
    setBackground(snap.bg);
    showSprite(snap.sprite);
    applyFaceDirect(snap.face);
    if (snap.bgm) playBgm(snap.bgm);

    if (snap.kind === "cghold") {
      // 「画だけ」ビート：CGを張り直す（テキスト窓は cg-active で隠れる）
      state.currentCg = null;                 // guard を外して必ず張り直す
      showCg(snap.cgHoldLine.cg);
    } else {
      showCg("");                             // CGを消してテキスト窓を戻す
      dom.speaker.textContent = snap.speaker;
      dom.text.textContent = snap.text;
      if (snap.kind === "choice") showChoices(snap.line);
    }
  }

  function goBack() {
    if (state.cardActive) return;                          // 転換カード中は無視
    if (!dom.title.classList.contains("hidden")) return;   // 本編中のみ
    if (state.history.length < 2) return;                  // これ以上戻れない
    state.history.pop();                                   // 現在のビートを捨て
    restoreSnapshot(state.history[state.history.length - 1]); // 直前を復元
  }

  async function boot() {
    try {
      if (INLINE) {
        // スタンドアロン：埋め込み済みデータを使う（fetch なし＝file:// で動く）
        state.script = INLINE.script;
        state.meta = INLINE.meta || {};
        state.cast = INLINE.cast || { characters: [] };
      } else {
        state.script = await loadJSON("script.json");
        state.meta = await loadJSON("meta.json").catch(() => ({}));
        state.cast = await loadJSON("cast.json").catch(() => ({ characters: [] }));
      }
    } catch (e) {
      dom.titleName.textContent = "バンドル読込エラー";
      dom.titleSub.textContent = String(e.message || e);
      return;
    }
    buildCastIndex();

    const m = state.meta || {};
    dom.titleName.textContent = m.title || state.script.title || "(無題)";
    dom.titleSub.textContent = m.subtitle || "";
    dom.titleAuthor.textContent = [m.author, m.publisher].filter(Boolean).join("　／　");
    dom.hudTitle.textContent = m.title || state.script.title || "";

    const coverUrl = await tryImage(`${ASSETS}/cover.jpg`);
    if (coverUrl) dom.cover.src = coverUrl; else dom.cover.style.display = "none";

    dom.startBtn.onclick = startGame;
    dom.textbox.onclick = advance;
    // CG（一枚絵）表示中はテキストボックスが非表示になるため、
    // CG 画像クリックでもテキスト送りできるようにする（#8 fix）。
    dom.cg.onclick = advance;
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowUp") {
        ev.preventDefault();
        goBack();                 // 上キー＝1ビート戻る
      } else if (ev.key === "Enter" || ev.key === " " || ev.key === "ArrowDown") {
        ev.preventDefault();
        advance();                // 下キー/Enter/Space＝進める
      }
    });

    // ミュートボタンのバインド（ボタンが index.html に存在する場合）
    const muteBtn = el("mute-btn");
    if (muteBtn) muteBtn.onclick = (e) => { e.stopPropagation(); toggleMute(); };
  }

  boot();
})();
