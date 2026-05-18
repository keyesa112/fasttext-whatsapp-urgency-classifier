/**
 * Real-time Urgent Message Notification System
 * Apotek K24 WhatsApp Monitoring
 */

class UrgentNotification {
  constructor() {
    this.audioElement = null;
    this.isPolling = false;
    this.soundReady = false;
    this.notificationReady = false;
    this.isPWA = window.matchMedia('(display-mode: standalone)').matches ||
                 window.navigator.standalone === true;
    this.swRegistration = null;
    this.permissionRetryBound = false;

    console.log(this.isPWA ? '📱 Running as PWA' : '🌐 Running in browser');

    this.init();
  }

  async init() {
    this.initAudio();
    await this.registerServiceWorker();
    await this.requestNotificationPermission();
    this.bindLifecycleEvents();
  }

  initAudio() {
    this.audioElement = new Audio('/static/sounds/urgent-alert.wav');
    this.audioElement.preload = 'auto';
    this.audioElement.playsInline = true;
    this.audioElement.crossOrigin = 'anonymous';

    this.tryAutoWarmup();
    this.setupAudioUnlock();
  }

  async tryAutoWarmup() {
    if (!this.audioElement || this.soundReady) return;

    try {
      this.audioElement.muted = true;
      this.audioElement.volume = 0;
      await this.audioElement.play();
      this.audioElement.pause();
      this.audioElement.currentTime = 0;
      this.audioElement.muted = false;
      this.audioElement.volume = 1;
      this.soundReady = true;
      localStorage.setItem('k24_sound_ready', '1');
      console.log('✅ Audio auto-warmup success');
    } catch (err) {
      console.warn('⚠️ Audio auto-warmup blocked:', err.message);
    }
  }

  setupAudioUnlock() {
    const unlockEvents = ['pointerdown', 'touchstart', 'keydown', 'focus'];

    const unlock = async () => {
      if (this.soundReady) return;
      await this.tryAutoWarmup();

      if (this.soundReady) {
        unlockEvents.forEach(event => window.removeEventListener(event, unlock));
      }
    };

    unlockEvents.forEach(event => {
      window.addEventListener(event, unlock, { passive: true });
    });
  }

  bindLifecycleEvents() {
    const retryInit = async () => {
      await this.tryAutoWarmup();
      await this.requestNotificationPermission();
    };

    window.addEventListener('pageshow', retryInit);
    window.addEventListener('focus', retryInit);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        retryInit();
      }
    });
  }

  async registerServiceWorker() {
    if (!('serviceWorker' in navigator)) {
      console.warn('⚠️ Service Worker not supported');
      return;
    }

    try {
      const registration = await navigator.serviceWorker.register('/static/js/sw.js');
      this.swRegistration = await navigator.serviceWorker.ready;
      console.log('✅ Service Worker registered:', registration.scope);
    } catch (err) {
      console.error('❌ SW registration failed:', err);
    }
  }

  async requestNotificationPermission() {
    if (!('Notification' in window)) {
      console.warn('⚠️ Notification API not supported');
      return;
    }

    if (Notification.permission === 'granted') {
      this.notificationReady = true;
      return;
    }

    if (Notification.permission === 'denied') {
      console.warn('⚠️ Notifications blocked by user');
      return;
    }

    try {
      const permission = await Notification.requestPermission();
      this.notificationReady = permission === 'granted';
      console.log('📬 Notification permission result:', permission);
    } catch (err) {
      console.warn('⚠️ Notification permission requires user gesture:', err.message);
      this.bindPermissionRetry();
    }
  }

  bindPermissionRetry() {
    if (this.permissionRetryBound) return;
    this.permissionRetryBound = true;

    const retry = async () => {
      if (Notification.permission !== 'default') {
        window.removeEventListener('pointerdown', retry);
        return;
      }

      try {
        const permission = await Notification.requestPermission();
        this.notificationReady = permission === 'granted';
        if (permission !== 'default') {
          window.removeEventListener('pointerdown', retry);
        }
      } catch (err) {
        console.warn('⚠️ Retry notification permission failed:', err.message);
      }
    };

    window.addEventListener('pointerdown', retry, { passive: true });
  }

  start(usePolling = false) {
    if (this.isPolling) return;

    if (usePolling) {
      console.log('⚠️ SSE tidak tersedia, fallback ke polling');
      this.isPolling = true;
      this.poll();
      this.pollingTimer = setInterval(() => this.poll(), 5000);
      return;
    }

    console.log('✅ Notification system ready (SSE mode)');
  }

  async handleUrgentEvent(data) {
    console.log('🔔 Urgent event dari SSE:', data);

    this.updateBadge(data.count || 1);
    this.playSound();
    await this.showNotification({
      title: `🚨 ${data.count || 1} Pesan Urgent Baru!`,
      body: data.preview || 'Ada pesan urgent masuk',
      url: '/messages/queue',
    });
    this.showToast(data);
  }

  async poll() {
    try {
      const response = await fetch('/api/messages/urgent?notified=0');
      const data = await response.json();

      if (data.new_urgent_count > 0) {
        this.updateBadge(data.new_urgent_count);
        this.playSound();
        await this.showNotification({
          title: `🚨 ${data.new_urgent_count} Pesan Urgent Baru!`,
          body: data.messages[0]?.message_text?.substring(0, 80),
          url: '/messages/queue',
        });
        this.showToast({
          count: data.new_urgent_count,
          messages: data.messages,
        });

        await this.markNotified(data.messages.map(m => m.id));
      }
    } catch (error) {
      console.error('❌ Polling error:', error);
    }
  }

  updateBadge(count) {
    const badge = document.getElementById('urgent-badge');
    if (badge) {
      badge.textContent = count;
      badge.classList.add('badge-pulse');
    }

    if ('setAppBadge' in navigator) {
      navigator.setAppBadge(count).catch(err => console.warn('Badge error:', err));
    }
  }

  async playSound() {
    if (!this.audioElement) return;

    if (!this.soundReady) {
      await this.tryAutoWarmup();
    }

    if (!this.soundReady) {
      console.warn('⚠️ Sound still locked by browser autoplay policy');
      if ('vibrate' in navigator) {
        navigator.vibrate([200, 100, 200]);
      }
      return;
    }

    try {
      this.audioElement.pause();
      this.audioElement.currentTime = 0;
      this.audioElement.muted = false;
      this.audioElement.volume = 1;
      await this.audioElement.play();
      console.log('🔊 Sound playing...');
    } catch (err) {
      console.error('❌ Play error:', err.message);
    }
  }

  async showNotification(data) {
    if (!this.notificationReady) {
      return;
    }

    const title = data.title || '🚨 Pesan Urgent Baru!';
    const body = data.body || 'Ada pesan urgent masuk';
    const options = {
      body,
      icon: '/static/img/apotek-icon-192.png',
      badge: '/static/img/apotek-icon-192.png',
      vibrate: [200, 100, 200],
      tag: 'urgent-message',
      renotify: true,
      requireInteraction: true,
      data: {
        url: data.url || '/messages/queue',
        timestamp: Date.now(),
      },
    };

    try {
      if (this.swRegistration) {
        await this.swRegistration.showNotification(title, options);
      } else {
        new Notification(title, options);
      }
    } catch (err) {
      console.error('❌ Notification error:', err);
    }
  }

  showToast(data) {
    const messages = data.messages || [];
    const count = data.count || messages.length || 1;
    const preview = messages[0]?.message_text?.substring(0, 60) || 'Ada pesan urgent masuk';
    const customer = messages[0]?.customer?.name || data.customer_name || '';

    if (typeof showToast === 'function') {
      showToast({
        type: 'danger',
        title: `🚨 ${count} Pesan Urgent Baru!`,
        body: customer ? `${customer}: ${preview}` : preview,
      });
    }
  }

  async markNotified(messageIds) {
    try {
      await fetch('/api/messages/mark-notified', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_ids: messageIds }),
      });
    } catch (error) {
      console.error('❌ Mark notified error:', error);
    }
  }
}

let urgentNotifier = null;

$(document).ready(function () {
  urgentNotifier = new UrgentNotification();
});
