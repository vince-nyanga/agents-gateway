/**
 * Agent Gateway Dashboard — client-side behaviours
 * (Theme toggle, HTMX config, CSRF, misc)
 */

// --- Theme Management ---
const THEME_KEY = 'agw-dashboard-theme';

function applyTheme(theme) {
  const html = document.documentElement;
  html.classList.remove('dark', 'light');
  if (theme === 'dark') html.classList.add('dark');
  else if (theme === 'light') html.classList.add('light');
  // 'auto' → no class, CSS media query handles it
}

function initTheme() {
  const themeMode = document.documentElement.dataset.themeMode || 'auto';
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved || themeMode);
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains('dark') ||
    (!document.documentElement.classList.contains('light') &&
     window.matchMedia('(prefers-color-scheme: dark)').matches);
  const next = isDark ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
});

// --- HTMX: inject CSRF token on all mutating requests ---
document.addEventListener('htmx:configRequest', (event) => {
  const method = (event.detail.verb || '').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
      event.detail.headers['X-CSRF-Token'] = csrfMeta.content;
    }
  }
});

// --- SSE Chat Streaming ---
function createAssistantBubble() {
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.innerHTML = `
    <div class="message-avatar" style="font-size:0.75rem;">AI</div>
    <div class="message-bubble"></div>
  `;
  return div;
}

function parseSSEEvents(buffer) {
  const events = [];
  const lines = buffer.split('\n');
  let currentEvent = null;
  let remaining = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // If this is the last line and doesn't end with newline, it's incomplete
    if (i === lines.length - 1 && !buffer.endsWith('\n')) {
      remaining = line;
      break;
    }

    if (line.startsWith('event: ')) {
      currentEvent = { type: line.slice(7).trim(), data: '' };
    } else if (line.startsWith('data: ') && currentEvent) {
      currentEvent.data = line.slice(6);
      try {
        currentEvent.data = JSON.parse(currentEvent.data);
      } catch(e) { /* keep as string */ }
      events.push(currentEvent);
      currentEvent = null;
    } else if (line === '' && currentEvent) {
      // Empty line ends an event
      events.push(currentEvent);
      currentEvent = null;
    }
  }

  return { parsed: events, remaining };
}

async function sendChatMessage(form) {
  const formData = new FormData(form);
  const msg = (formData.get('message') || '').trim();
  if (!msg) return;

  const messagesArea = document.getElementById('messages');
  const textarea = document.getElementById('chat-message-input');
  const submitBtn = form.querySelector('button[type="submit"]');

  // Optimistic user bubble
  appendUserMessage(msg);
  textarea.value = '';
  textarea.style.height = 'auto';

  // Disable submit while streaming
  if (submitBtn) submitBtn.disabled = true;

  // Show loading indicator
  const indicator = document.getElementById('chat-loading');
  if (indicator) indicator.style.display = 'flex';

  // Create assistant bubble
  const bubble = createAssistantBubble();
  messagesArea.appendChild(bubble);
  messagesArea.scrollTop = messagesArea.scrollHeight;

  const bubbleContent = bubble.querySelector('.message-bubble');
  let fullText = '';

  try {
    const response = await fetch('/dashboard/chat/stream', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      bubbleContent.textContent = 'Error: ' + response.statusText;
      bubble.classList.add('message-error');
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let firstToken = true;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const result = parseSSEEvents(buffer);
      buffer = result.remaining;

      for (const event of result.parsed) {
        if (event.type === 'token') {
          if (firstToken) {
            // Hide loading indicator on first token
            if (indicator) indicator.style.display = 'none';
            firstToken = false;
          }
          fullText += event.data.content || '';
          bubbleContent.textContent = fullText;
          messagesArea.scrollTop = messagesArea.scrollHeight;
        } else if (event.type === 'session') {
          // Update session ID
          const field = document.getElementById('session-id-field');
          if (field && event.data.session_id) {
            field.value = event.data.session_id;
          }
        } else if (event.type === 'done') {
          // Render final markdown
          if (fullText && typeof marked !== 'undefined') {
            bubbleContent.innerHTML = marked.parse(fullText);
          }
          // Update session ID from done event too
          const field = document.getElementById('session-id-field');
          if (field && event.data.session_id) {
            field.value = event.data.session_id;
          }
        } else if (event.type === 'error') {
          const errMsg = event.data.message || 'An error occurred';
          if (event.data.setup_url) {
            bubbleContent.innerHTML = escapeHtml(errMsg) +
              ' <a href="' + escapeHtml(event.data.setup_url) + '" class="btn btn-primary btn-sm" style="margin-left:var(--space-2)">Setup</a>';
          } else {
            bubbleContent.textContent = errMsg;
          }
          bubble.classList.add('message-error');
        }
      }
    }
  } catch (err) {
    bubbleContent.textContent = 'Connection error: ' + err.message;
    bubble.classList.add('message-error');
  } finally {
    if (indicator) indicator.style.display = 'none';
    if (submitBtn) submitBtn.disabled = false;
    messagesArea.scrollTop = messagesArea.scrollHeight;
  }
}

// Wire up chat form submit
document.addEventListener('DOMContentLoaded', () => {
  const chatForm = document.getElementById('chat-form');
  if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      sendChatMessage(chatForm);
    });
  }
});

// --- Chat: Enter to send, Shift+Enter for newline ---
document.addEventListener('DOMContentLoaded', () => {
  const textarea = document.getElementById('chat-message-input');
  if (!textarea) return;

  // Auto-resize textarea
  function resizeTextarea() {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 128) + 'px';
  }

  textarea.addEventListener('input', resizeTextarea);

  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const form = textarea.closest('form');
      if (form && textarea.value.trim()) {
        sendChatMessage(form);
      }
    }
  });
});

function appendUserMessage(text) {
  const area = document.getElementById('messages');
  if (!area) return;
  const div = document.createElement('div');
  div.className = 'message message-user htmx-added';
  div.innerHTML = `
    <div class="message-avatar">U</div>
    <div class="message-bubble">${escapeHtml(text)}</div>
  `;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// --- Copy-on-click for execution IDs ---
document.addEventListener('click', (e) => {
  const copyable = e.target.closest('.copyable[data-copy]');
  if (!copyable) return;
  e.preventDefault();
  navigator.clipboard.writeText(copyable.dataset.copy).then(() => {
    const toast = document.createElement('span');
    toast.className = 'copy-toast';
    toast.textContent = 'Copied!';
    copyable.appendChild(toast);
    setTimeout(() => toast.remove(), 1300);
  });
});

// --- Trace: toggle step detail panels ---
document.addEventListener('click', (e) => {
  const header = e.target.closest('.trace-card-header');
  if (!header) return;
  const body = header.closest('.trace-card')?.querySelector('.trace-card-body');
  if (body) {
    body.classList.toggle('hidden');
    const chevron = header.querySelector('.chevron');
    if (chevron) chevron.style.transform = body.classList.contains('hidden') ? '' : 'rotate(180deg)';
  }
});

// --- Mobile sidebar toggle ---
document.addEventListener('DOMContentLoaded', () => {
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('sidebar-overlay');

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      sidebarToggle.setAttribute('aria-expanded', sidebar.classList.contains('open'));
    });
    overlay?.addEventListener('click', () => {
      sidebar.classList.remove('open');
      sidebarToggle.setAttribute('aria-expanded', 'false');
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
        sidebarToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
});

// --- Agent selector in chat: update hidden input and handle personal agents ---
function updateChatForAgent(selector) {
  const selected = selector.options[selector.selectedIndex];
  if (!selected) return;

  const isPersonal = selected.dataset.personal === 'true';
  const isConfigured = selected.dataset.configured === 'true';
  const banner = document.getElementById('setup-required-banner');
  const inputArea = document.getElementById('chat-input-area');
  const setupLink = document.getElementById('setup-required-link');

  if (isPersonal && !isConfigured) {
    if (banner) banner.style.display = 'block';
    if (inputArea) inputArea.style.display = 'none';
    if (setupLink) setupLink.href = '/dashboard/agents/' + selected.value + '/setup';
  } else {
    if (banner) banner.style.display = 'none';
    if (inputArea) inputArea.style.display = '';
  }
}

document.addEventListener('change', (e) => {
  if (e.target && e.target.id === 'agent-selector') {
    const url = new URL(window.location.href);
    url.searchParams.set('agent_id', e.target.value);
    window.location.href = url.toString();
  }
});

// Check personal agent status on page load
document.addEventListener('DOMContentLoaded', () => {
  const selector = document.getElementById('agent-selector');
  if (selector) updateChatForAgent(selector);
});
