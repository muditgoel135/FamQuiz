/* FamQuiz shared-game notifier.
 * SSE primary (GET /api/game/events), 4s polling fallback.
 * Banner + auto-redirect to /gameplay at live, respecting
 * game_reminders and Do-not-disturb (banner only, no redirect/sound).
 */
(function () {
    var box = document.getElementById("game-notify");
    if (!box) return;
    var textEl = document.getElementById("game-notify-text");
    var countEl = document.getElementById("game-notify-countdown");
    var joinBtn = document.getElementById("game-notify-join");
    var dismissBtn = document.getElementById("game-notify-dismiss");

    var T = window.I18N_GAME || {};
    function t(key, fallback) {
        return T[key] || fallback;
    }

    var statusUrl = box.dataset.statusUrl;
    var eventsUrl = box.dataset.eventsUrl;
    var joinUrl = box.dataset.joinUrl;
    var gameplayUrl = box.dataset.gameplayUrl;
    var authenticated = box.dataset.authenticated === "1";
    var remindersOn = box.dataset.reminders === "1";
    var userStatus = (box.dataset.userStatus || "").toLowerCase();
    var dnd = userStatus === "do not disturb";
    var quiet = dnd || !remindersOn;
    var onGameplay = window.location.pathname.indexOf("/gameplay") !== -1;

    if (!authenticated) return;

    var current = null; // last game dict
    var dismissedFor = null; // "id:status" the user dismissed
    var notifiedFor = null; // "id:status" already notified
    var pollTimer = null;
    var countdownTimer = null;
    var es = null;

    function fmtMs(ms) {
        var s = Math.max(0, Math.ceil(ms / 1000));
        var m = Math.floor(s / 60);
        var r = s % 60;
        return (m < 10 ? "0" + m : "" + m) + ":" + (r < 10 ? "0" + r : "" + r);
    }

    function key(game) {
        return game ? game.id + ":" + game.status : null;
    }

    function show(game) {
        current = game;
        if (!game) {
            box.hidden = true;
            return;
        }
        if (dismissedFor === key(game)) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        var label;
        if (game.status === "active") {
            label = t("live", "Game live — opening…");
        } else {
            label = t("waitingTapJoin", "A family game is waiting — tap Join!");
        }
        textEl.textContent = label;
        tickCountdown();
    }

    function tickCountdown() {
        if (!current) {
            countEl.textContent = "";
            return;
        }
        if (current.status === "lobby") {
            countEl.textContent = t("startingIn", "Game starting in") + " " + fmtMs(current.starts_in_ms);
        } else if (current.status === "active") {
            countEl.textContent = t("live", "Game live — opening…");
        } else {
            countEl.textContent = "";
        }
    }

    function maybeNotify(game) {
        if (!game || quiet) return;
        if (notifiedFor === key(game)) return;
        notifiedFor = key(game);
        try {
            if ("Notification" in window && Notification.permission === "granted") {
                new Notification("FamQuiz", {
                    body: t("waitingTapJoin", "A family game is waiting — tap Join!")
                });
            } else if ("Notification" in window && Notification.permission === "default") {
                try { Notification.requestPermission(); } catch (e) { /* ignore */ }
            }
        } catch (e) { /* notifications are best-effort */ }
    }

    function maybeRedirect(game) {
        if (!game || game.status !== "active") return;
        if (quiet || onGameplay) return;
        if (dismissedFor === key(game)) return;
        window.location.href = gameplayUrl;
    }

    function handleGame(game) {
        if (!game) {
            current = null;
            box.hidden = true;
            return;
        }
        var changed = key(game) !== key(current);
        show(game);
        if (changed) maybeNotify(game);
        maybeRedirect(game);
    }

    function fetchStatus() {
        return fetch(statusUrl, { headers: { Accept: "application/json" } })
            .then(function (resp) {
                if (!resp.ok) throw new Error("status " + resp.status);
                return resp.json();
            })
            .then(function (body) {
                handleGame(body.active_game || null);
            })
            .catch(function () { /* keep last state; SSE/poll retries */ });
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(fetchStatus, 4000);
    }

    function connectSSE() {
        if (!window.EventSource) {
            startPolling();
            return;
        }
        try {
            es = new EventSource(eventsUrl);
        } catch (e) {
            startPolling();
            return;
        }
        var onData = function (ev) {
            try {
                var snap = JSON.parse(ev.data);
                if (snap && snap.active_game !== undefined) {
                    handleGame(snap.active_game);
                } else if (snap && snap.type) {
                    if (snap.type === "game-none" || snap.type === "game-cancelled") {
                        handleGame(null);
                    } else if (snap.type === "game-pending" || snap.type === "game-live") {
                        handleGame({
                            id: snap.id,
                            status: snap.type === "game-live" ? "active" : "lobby",
                            starts_in_ms: snap.starts_in_ms || 0,
                            starts_at: snap.starts_at,
                            expires_at: snap.expires_at,
                            num_questions: snap.num_questions,
                            difficulty: snap.difficulty,
                            powerups_enabled: snap.powerups_enabled
                        });
                    }
                }
            } catch (e) { /* ignore malformed event */ }
        };
        es.addEventListener("snapshot", onData);
        es.addEventListener("update", onData);
        es.addEventListener("message", onData);
        es.addEventListener("end", function () {
            try { es.close(); } catch (e) { /* ignore */ }
        });
        es.onerror = function () {
            try { es.close(); } catch (e) { /* ignore */ }
            es = null;
            startPolling();
        };
    }

    if (joinBtn) {
        joinBtn.addEventListener("click", function () {
            fetch(joinUrl, { method: "POST" })
                .then(function () {
                    window.location.href = gameplayUrl;
                })
                .catch(function () {
                    window.location.href = gameplayUrl;
                });
        });
    }
    if (dismissBtn) {
        dismissBtn.addEventListener("click", function () {
            dismissedFor = key(current);
            box.hidden = true;
        });
    }

    countdownTimer = setInterval(tickCountdown, 1000);
    fetchStatus();
    connectSSE();

    // Let the homepage Start button refresh immediately after creating a lobby.
    window.FamQuizNotify = {
        refresh: fetchStatus,
        get current() { return current; }
    };
})();
