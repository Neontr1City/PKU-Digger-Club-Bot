document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = '已复制 ✓';
    } catch {
      button.textContent = '请手动选择上方文字复制';
    }
  });
});

// Animate each section once as it enters view; never hide content before JS loads.
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
if ('IntersectionObserver' in window && !motionPreference.matches) {
  const reveal = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        if (!motionPreference.matches) entry.target.classList.add('motion-arrive');
        reveal.unobserve(entry.target);
      }
    }
  }, { threshold: 0.08 });
  document.querySelectorAll('.page-heading, .duel, .track-fields, .login-box').forEach(section => {
    reveal.observe(section);
  });
}

// Refresh only the tally panel, preserving unsaved admin forms.
const liveVotes = document.querySelector('[data-votes-url]');
if (liveVotes) {
  let refreshing = false;
  const enableRefresh = () => {
    liveVotes.querySelector('[data-live-auto]').hidden = false;
  };
  const refreshVotes = async () => {
    if (refreshing) return;
    refreshing = true;
    const button = liveVotes.querySelector('[data-refresh-votes]');
    if (button) button.disabled = true;
    try {
      const response = await fetch(liveVotes.dataset.votesUrl, { cache: 'no-store' });
      if (response.redirected) {
        clearInterval(refreshTimer);
        liveVotes.replaceChildren();
        const link = document.createElement('a');
        link.href = response.url;
        link.className = 'button secondary';
        link.textContent = '登录已过期，重新登录查看票数 →';
        liveVotes.append(link);
        return;
      }
      if (!response.ok) throw new Error('Refresh failed');
      const content = await response.text();
      liveVotes.innerHTML = content;
      enableRefresh();
    } catch {
      liveVotes.querySelector('[data-refresh-status]').textContent = '更新失败，当前显示上次数据。请稍后刷新。';
    } finally {
      refreshing = false;
      const currentButton = liveVotes.querySelector('[data-refresh-votes]');
      if (currentButton) currentButton.disabled = false;
    }
  };
  liveVotes.addEventListener('click', event => {
    if (event.target.closest('[data-refresh-votes]')) refreshVotes();
  });
  const refreshTimer = setInterval(() => {
    if (!document.hidden) refreshVotes();
  }, 15000);
  enableRefresh();
}
