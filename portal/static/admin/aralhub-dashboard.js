(() => {
  const url = document.currentScript.dataset.liveUrl;
  const status = document.getElementById('campusLiveStatus');
  let timer, busy = false, stopped = false;
  async function refresh() {
    clearTimeout(timer);
    if (stopped || document.hidden || busy) return;
    busy = true;
    try {
      const response = await fetch(url, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok || response.redirected) throw new Error('Connection interrupted');
      const data = await response.json();
      if (stopped) return;
      document.querySelectorAll('[data-campus-stat]').forEach(element => { element.textContent = data[element.dataset.campusStat]; });
      status.textContent = 'Live · updates every 5 seconds'; status.classList.remove('reconnecting');
    } catch (error) {
      status.textContent = 'Reconnecting · displayed records are kept'; status.classList.add('reconnecting');
    } finally {
      busy = false;
      if (!stopped && !document.hidden) timer = setTimeout(refresh, 5000);
    }
  }
  document.addEventListener('visibilitychange', () => { clearTimeout(timer); if (!document.hidden) refresh(); });
  window.addEventListener('online', refresh);
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  window.addEventListener('pageshow', () => { stopped = false; refresh(); });
  timer = setTimeout(refresh, 5000);
})();
