/**
 * Life Context Chat Widget
 *
 * Floating chat button (bottom-right) that opens a sliding right panel.
 * Handles:
 *   - Session init / resume via GET /api/chat/session
 *   - SSE streaming replies via POST /api/chat/message
 *   - Returning-user AI opener via POST /api/chat/opener
 *   - End session (compression) via POST /api/chat/end
 *   - beforeunload warning when an uncompressed session is open
 *   - Starter prompt chips for first-time users
 */

(function () {
  'use strict';

  // ── State ───────────────────────────────────────────────────────────────
  var sessionId = null;
  var isStreaming = false;
  var hasUncompressedSession = false;

  // ── DOM refs (set after inject) ─────────────────────────────────────────
  var widget, panel, msgList, inputEl, sendBtn, endBtn, chipArea;

  // ── Inject widget HTML + CSS ─────────────────────────────────────────────
  function injectStyles() {
    var style = document.createElement('style');
    style.textContent = [
      /* Floating button */
      '.chat-fab{position:fixed;bottom:1.5rem;right:1.5rem;z-index:900;',
      'width:52px;height:52px;border-radius:50%;background:var(--accent);',
      'color:#fff;border:none;cursor:pointer;font-size:1.4rem;line-height:52px;',
      'text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.4);transition:background 0.15s;}',
      '.chat-fab:hover{background:var(--accent-hover);}',

      /* Panel */
      '.chat-panel{position:fixed;top:0;right:0;bottom:0;z-index:901;',
      'width:420px;max-width:100vw;background:var(--surface);',
      'border-left:1px solid var(--border);display:flex;flex-direction:column;',
      'transform:translateX(100%);transition:transform 0.25s ease;box-shadow:-4px 0 24px rgba(0,0,0,0.4);}',
      '.chat-panel.open{transform:translateX(0);}',

      /* Panel header */
      '.chat-panel__header{display:flex;align-items:center;justify-content:space-between;',
      'padding:1rem 1.25rem;border-bottom:1px solid var(--border);flex-shrink:0;}',
      '.chat-panel__title{font-size:0.95rem;font-weight:700;color:var(--text);}',
      '.chat-panel__close{background:none;border:none;color:var(--muted);cursor:pointer;',
      'font-size:1.2rem;line-height:1;padding:0.2rem;}',
      '.chat-panel__close:hover{color:var(--text);}',

      /* Resume notice */
      '.chat-resume-notice{margin:0.75rem 1rem 0;padding:0.6rem 0.85rem;',
      'background:rgba(245,166,35,0.1);border:1px solid rgba(245,166,35,0.35);',
      'border-radius:var(--radius);font-size:0.8rem;color:#f7c96a;}',

      /* Message list */
      '.chat-messages{flex:1;overflow-y:auto;padding:1rem;display:flex;',
      'flex-direction:column;gap:0.75rem;}',

      /* Bubbles */
      '.chat-bubble{max-width:88%;padding:0.65rem 0.9rem;border-radius:12px;',
      'font-size:0.9rem;line-height:1.55;word-break:break-word;white-space:pre-wrap;}',
      '.chat-bubble--user{align-self:flex-end;background:var(--accent);color:#fff;',
      'border-bottom-right-radius:3px;}',
      '.chat-bubble--assistant{align-self:flex-start;background:var(--bg);',
      'border:1px solid var(--border);color:var(--text);border-bottom-left-radius:3px;}',
      '.chat-bubble--system{align-self:center;background:none;color:var(--muted);',
      'font-size:0.8rem;font-style:italic;text-align:center;}',

      /* Starter chips */
      '.chat-chips{display:flex;flex-direction:column;gap:0.4rem;',
      'margin-top:0.5rem;align-self:flex-start;}',
      '.chat-chip{background:rgba(108,143,255,0.1);border:1px solid rgba(108,143,255,0.35);',
      'color:var(--accent);border-radius:6px;padding:0.4rem 0.75rem;font-size:0.82rem;',
      'cursor:pointer;text-align:left;transition:background 0.15s;}',
      '.chat-chip:hover{background:rgba(108,143,255,0.2);}',

      /* Typing indicator */
      '.chat-typing{display:flex;gap:4px;align-items:center;padding:0.4rem 0.6rem;}',
      '.chat-typing span{width:7px;height:7px;border-radius:50%;background:var(--muted);',
      'animation:chatBounce 1s infinite ease-in-out;}',
      '.chat-typing span:nth-child(2){animation-delay:0.2s;}',
      '.chat-typing span:nth-child(3){animation-delay:0.4s;}',
      '@keyframes chatBounce{0%,80%,100%{transform:scale(0.8)}40%{transform:scale(1.2)}}',

      /* Input row */
      '.chat-input-row{display:flex;gap:0.5rem;padding:0.75rem 1rem;',
      'border-top:1px solid var(--border);flex-shrink:0;}',
      '.chat-input-row textarea{flex:1;resize:none;height:2.6rem;max-height:120px;',
      'overflow-y:auto;font-size:0.9rem;padding:0.5rem 0.75rem;line-height:1.4;}',
      '.chat-send-btn{align-self:flex-end;padding:0.5rem 0.9rem;font-size:0.85rem;}',

      /* End session button */
      '.chat-end-row{padding:0.5rem 1rem 0.75rem;flex-shrink:0;}',
      '.chat-end-btn{width:100%;font-size:0.85rem;padding:0.5rem;',
      'background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.35);',
      'color:var(--danger);border-radius:var(--radius);cursor:pointer;',
      'transition:background 0.15s;}',
      '.chat-end-btn:hover:not(:disabled){background:rgba(255,107,107,0.2);}',
      '.chat-end-btn:disabled{opacity:0.4;cursor:not-allowed;}',
    ].join('');
    document.head.appendChild(style);
  }

  function injectHTML() {
    var fab = document.createElement('button');
    fab.className = 'chat-fab';
    fab.id = 'chat-fab';
    fab.setAttribute('aria-label', 'Open financial profile chat');
    fab.innerHTML = '&#128172;'; // speech bubble

    var html = [
      '<div class="chat-panel" id="chat-panel">',
      '  <div class="chat-panel__header">',
      '    <span class="chat-panel__title">&#128172; Financial Profile Chat</span>',
      '    <button class="chat-panel__close" id="chat-close" aria-label="Close chat">&times;</button>',
      '  </div>',
      '  <div id="chat-resume-notice" class="chat-resume-notice" style="display:none;">',
      '    You have an unfinished session. Click <strong>End Chat Session</strong> when you\'re done to save your context.',
      '  </div>',
      '  <div class="chat-messages" id="chat-messages"></div>',
      '  <div class="chat-end-row">',
      '    <button class="chat-end-btn" id="chat-end-btn" disabled>End Chat Session</button>',
      '  </div>',
      '  <div class="chat-input-row">',
      '    <textarea id="chat-input" placeholder="Type a message\u2026" rows="1"></textarea>',
      '    <button class="btn btn--primary chat-send-btn" id="chat-send-btn">Send</button>',
      '  </div>',
      '</div>',
    ].join('');

    var wrapper = document.createElement('div');
    wrapper.innerHTML = html;

    document.body.appendChild(fab);
    while (wrapper.firstChild) {
      document.body.appendChild(wrapper.firstChild);
    }

    widget = document.getElementById('chat-fab');
    panel  = document.getElementById('chat-panel');
    msgList = document.getElementById('chat-messages');
    inputEl = document.getElementById('chat-input');
    sendBtn = document.getElementById('chat-send-btn');
    endBtn  = document.getElementById('chat-end-btn');
    chipArea = null; // created dynamically
  }

  // ── Open / close ────────────────────────────────────────────────────────
  function openPanel() {
    panel.classList.add('open');
    widget.style.display = 'none';
    if (sessionId === null) {
      initSession();
    }
  }

  function closePanel() {
    panel.classList.remove('open');
    widget.style.display = '';
  }

  // ── Message rendering ────────────────────────────────────────────────────
  function addBubble(role, text) {
    var cls = role === 'user' ? 'chat-bubble--user'
            : role === 'assistant' ? 'chat-bubble--assistant'
            : 'chat-bubble--system';
    var div = document.createElement('div');
    div.className = 'chat-bubble ' + cls;
    div.textContent = text;
    msgList.appendChild(div);
    scrollToBottom();
    return div;
  }

  function addTypingIndicator() {
    var wrap = document.createElement('div');
    wrap.className = 'chat-bubble chat-bubble--assistant';
    wrap.id = 'chat-typing';
    wrap.innerHTML = '<div class="chat-typing"><span></span><span></span><span></span></div>';
    msgList.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function removeTypingIndicator() {
    var el = document.getElementById('chat-typing');
    if (el) el.remove();
  }

  function addChips(chips) {
    var container = document.createElement('div');
    container.className = 'chat-chips';
    chips.forEach(function (text) {
      var btn = document.createElement('button');
      btn.className = 'chat-chip';
      btn.textContent = text;
      btn.addEventListener('click', function () {
        container.remove();
        sendMessage(text);
      });
      container.appendChild(btn);
    });
    msgList.appendChild(container);
    scrollToBottom();
  }

  function scrollToBottom() {
    msgList.scrollTop = msgList.scrollHeight;
  }

  // ── Session init ─────────────────────────────────────────────────────────
  function initSession() {
    fetch('/api/chat/session')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        sessionId = data.session_id;

        if (data.is_resumed) {
          // Reload existing messages
          data.messages.forEach(function (m) {
            addBubble(m.role, m.content);
          });
          // Only enable End and warn on unload if the user actually said something.
          var hasUserMsgs = data.messages.some(function (m) { return m.role === 'user'; });
          if (hasUserMsgs) {
            document.getElementById('chat-resume-notice').style.display = '';
            hasUncompressedSession = true;
            endBtn.disabled = false;
          }
        } else {
          // Fresh session — show intro
          var intro = data.intro;
          if (intro.type === 'static') {
            addBubble('assistant', intro.content);
            if (intro.chips && intro.chips.length) {
              addChips(intro.chips);
            }
          } else {
            // ai_opener — stream a personalized opener, then show update chips
            streamOpener(intro.chips || []);
          }
        }
      })
      .catch(function (err) {
        addBubble('system', 'Failed to load session: ' + err.message);
      });
  }

  // ── Stream AI opener (returning user) ───────────────────────────────────
  function streamOpener(chips) {
    addTypingIndicator();
    var bubble = null;
    var done = false;

    function finish() {
      if (done) return;
      done = true;
      if (chips && chips.length) {
        addChips(chips);
      }
    }

    fetch('/api/chat/opener', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }).then(function (resp) {
      if (!resp.ok) throw new Error('Opener request failed');
      removeTypingIndicator();
      bubble = addBubble('assistant', '');

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) { finish(); return; }
          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop();
          lines.forEach(function (line) {
            if (!line.startsWith('data: ')) return;
            var token = line.slice(6);
            if (token === '[DONE]') { finish(); return; }
            if (token.startsWith('[ERROR]')) {
              bubble.textContent = token.slice(8);
              finish();
              return;
            }
            bubble.textContent += token.replace(/\\n/g, '\n');
            scrollToBottom();
          });
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      removeTypingIndicator();
      addBubble('assistant', 'Hi! I\'m here to help update your financial profile. What would you like to discuss today?');
      finish();
    });
  }

  // ── Send a message ───────────────────────────────────────────────────────
  function sendMessage(text) {
    if (!text || !text.trim() || isStreaming || sessionId === null) return;
    text = text.trim();

    addBubble('user', text);
    inputEl.value = '';
    autoResizeInput();

    isStreaming = true;
    sendBtn.disabled = true;
    endBtn.disabled = true;

    var typingEl = addTypingIndicator();
    var bubble = null;

    fetch('/api/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, content: text }),
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().then(function (d) {
          throw new Error(d.detail || 'Request failed');
        });
      }
      removeTypingIndicator();
      bubble = addBubble('assistant', '');

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            finishStreaming();
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop();
          lines.forEach(function (line) {
            if (!line.startsWith('data: ')) return;
            var token = line.slice(6);
            if (token === '[DONE]') {
              finishStreaming();
              return;
            }
            if (token.startsWith('[ERROR]')) {
              bubble.textContent = 'Error: ' + token.slice(8);
              finishStreaming();
              return;
            }
            bubble.textContent += token.replace(/\\n/g, '\n');
            scrollToBottom();
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      removeTypingIndicator();
      addBubble('system', 'Error: ' + err.message);
      finishStreaming();
    });
  }

  function finishStreaming() {
    isStreaming = false;
    sendBtn.disabled = false;
    hasUncompressedSession = true;
    endBtn.disabled = false;
    inputEl.focus();
  }

  // ── End session ──────────────────────────────────────────────────────────
  function endSession() {
    if (isStreaming || sessionId === null) return;

    if (!confirm('End this chat session? The AI will compress our conversation into your financial context block. This cannot be undone.')) {
      return;
    }

    endBtn.disabled = true;
    sendBtn.disabled = true;
    addBubble('system', 'Compressing your financial context\u2026');

    fetch('/api/chat/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          hasUncompressedSession = false;
          sessionId = null;
          endBtn.disabled = true;
          sendBtn.disabled = true;
          inputEl.disabled = true;
          if (data.empty) {
            addBubble('system', 'Session ended. No messages were sent, so your profile was not changed.');
          } else {
            addBubble('system', 'Done! Your financial profile has been updated (v' + data.version + '). You can close this panel.');
            // Remove the amber banner from the dashboard if present
            var banner = document.getElementById('life-context-nudge');
            if (banner) banner.remove();
          }
        } else {
          addBubble('system', 'Something went wrong. Please try again.');
          endBtn.disabled = false;
          sendBtn.disabled = false;
        }
      }).catch(function (err) {
        addBubble('system', 'Error: ' + err.message);
        endBtn.disabled = false;
        sendBtn.disabled = false;
      });
  }

  // ── Input auto-resize ────────────────────────────────────────────────────
  function autoResizeInput() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  }

  // ── beforeunload warning ─────────────────────────────────────────────────
  window.addEventListener('beforeunload', function (e) {
    if (hasUncompressedSession) {
      e.preventDefault();
      e.returnValue = 'You have an unfinished chat session. Click "End Chat Session" to save your context before leaving.';
    }
  });

  // ── Wire events ──────────────────────────────────────────────────────────
  function wireEvents() {
    document.getElementById('chat-fab').addEventListener('click', openPanel);
    document.getElementById('chat-close').addEventListener('click', closePanel);

    sendBtn.addEventListener('click', function () {
      sendMessage(inputEl.value);
    });

    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage(inputEl.value);
      }
    });

    inputEl.addEventListener('input', autoResizeInput);

    endBtn.addEventListener('click', endSession);
  }

  // ── Bootstrap ────────────────────────────────────────────────────────────
  function init() {
    injectStyles();
    injectHTML();
    wireEvents();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
