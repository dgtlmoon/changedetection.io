/**
 * changedetection.io Browser Push Notifications
 * Handles service worker registration, push subscription management, and notification permissions
 */

class BrowserNotifications {
    constructor() {
        this.serviceWorkerRegistration = null;
        this.vapidPublicKey = null;
        this.isSubscribed = false;
        this.init();
    }

    async init() {
        if (!this.isSupported()) {
            console.warn('Push notifications are not supported in this browser');
            return;
        }

        try {
            // Get VAPID public key from server
            await this.fetchVapidPublicKey();
            
            // Register service worker
            await this.registerServiceWorker();
            
            // Initialize UI elements
            this.initializeUI();
            
            // Set up notification URL monitoring
            this.setupNotificationUrlMonitoring();
            
        } catch (error) {
            console.error('Failed to initialize browser notifications:', error);
        }
    }

    isSupported() {
        return 'serviceWorker' in navigator && 
               'PushManager' in window && 
               'Notification' in window;
    }

    async fetchVapidPublicKey() {
        try {
            const response = await fetch('/browser-notifications-api/vapid-public-key');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const data = await response.json();
            this.vapidPublicKey = data.publicKey;
        } catch (error) {
            console.error('Failed to fetch VAPID public key:', error);
            throw error;
        }
    }

    async registerServiceWorker() {
        try {
            this.serviceWorkerRegistration = await navigator.serviceWorker.register('/service-worker.js', {
                scope: '/'
            });

            console.log('Service Worker registered successfully');

            // Wait for service worker to be ready
            await navigator.serviceWorker.ready;

        } catch (error) {
            console.error('Service Worker registration failed:', error);
            throw error;
        }
    }

    initializeUI() {
        // Bind event handlers to existing elements in the template
        this.bindEventHandlers();
        
        // Update UI based on current permission state
        this.updatePermissionStatus();
    }

    bindEventHandlers() {
        const enableBtn = document.querySelector('#enable-notifications-btn');
        const testBtn = document.querySelector('#test-notification-btn');

        if (enableBtn) {
            enableBtn.addEventListener('click', () => this.requestNotificationPermission());
        }

        if (testBtn) {
            testBtn.addEventListener('click', () => this.sendTestNotification());
        }
    }

    setupNotificationUrlMonitoring() {
        // Monitor the notification URLs textarea for browser:// URLs
        const notificationUrlsField = document.querySelector('textarea[name*="notification_urls"]');
        if (notificationUrlsField) {
            const checkForBrowserUrls = async () => {
                const urls = notificationUrlsField.value || '';
                const hasBrowserUrls = /browser:\/\//.test(urls);
                
                // If browser URLs are detected and we're not subscribed, auto-subscribe
                if (hasBrowserUrls && !this.isSubscribed && Notification.permission === 'default') {
                    const shouldSubscribe = confirm('Browser notifications detected! Would you like to enable browser notifications now?');
                    if (shouldSubscribe) {
                        await this.requestNotificationPermission();
                    }
                } else if (hasBrowserUrls && !this.isSubscribed && Notification.permission === 'granted') {
                    // Permission already granted but not subscribed - auto-subscribe silently
                    console.log('Auto-subscribing to browser notifications...');
                    await this.subscribe();
                }
            };
            
            // Check immediately
            checkForBrowserUrls();
            
            // Check on input changes
            notificationUrlsField.addEventListener('input', checkForBrowserUrls);
        }
    }

    async updatePermissionStatus() {
        const statusElement = document.querySelector('#permission-status');
        const enableBtn = document.querySelector('#enable-notifications-btn');
        const testBtn = document.querySelector('#test-notification-btn');

        if (!statusElement) return;

        const permission = Notification.permission;
        statusElement.textContent = permission;
        statusElement.className = `permission-${permission}`;

        // Show/hide controls based on permission
        if (permission === 'default') {
            if (enableBtn) enableBtn.style.display = 'inline-block';
            if (testBtn) testBtn.style.display = 'none';
        } else if (permission === 'granted') {
            if (enableBtn) enableBtn.style.display = 'none';
            if (testBtn) testBtn.style.display = 'inline-block';
        } else { // denied
            if (enableBtn) enableBtn.style.display = 'none';
            if (testBtn) testBtn.style.display = 'none';
        }
    }

    async requestNotificationPermission() {
        try {
            const permission = await Notification.requestPermission();
            this.updatePermissionStatus();
            
            if (permission === 'granted') {
                console.log('Notification permission granted');
                // Automatically subscribe to browser notifications
                this.subscribe();
            } else {
                console.log('Notification permission denied');
            }
        } catch (error) {
            console.error('Error requesting notification permission:', error);
        }
    }

    async subscribe() {
        if (Notification.permission !== 'granted') {
            alert('Please enable notifications first');
            return;
        }

        if (this.isSubscribed) {
            console.log('Already subscribed to browser notifications');
            return;
        }

        try {
            // First, try to clear any existing subscription with different keys
            await this.clearExistingSubscription();

            // Create push subscription
            const subscription = await this.serviceWorkerRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: this.urlBase64ToUint8Array(this.vapidPublicKey)
            });

            // Send subscription to server
            const response = await fetch('/browser-notifications-api/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                },
                body: JSON.stringify({
                    subscription: subscription.toJSON()
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // Store subscription status
            this.isSubscribed = true;
            
            console.log('Successfully subscribed to browser notifications');

        } catch (error) {
            console.error('Failed to subscribe to browser notifications:', error);
            
            // Show user-friendly error message
            if (error.message.includes('different applicationServerKey')) {
                this.showSubscriptionConflictDialog(error);
            } else {
                alert(`Failed to subscribe: ${error.message}`);
            }
        }
    }

    async unsubscribe() {
        try {
            if (!this.isSubscribed) return;

            // Get current subscription
            const subscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
            if (!subscription) {
                this.isSubscribed = false;
                return;
            }

            // Unsubscribe from server
            const response = await fetch('/browser-notifications-api/unsubscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                },
                body: JSON.stringify({
                    subscription: subscription.toJSON()
                })
            });

            if (!response.ok) {
                console.warn(`Server unsubscribe failed: ${response.status}`);
            }

            // Unsubscribe locally
            await subscription.unsubscribe();

            // Update status
            this.isSubscribed = false;
            
            console.log('Unsubscribed from browser notifications');

        } catch (error) {
            console.error('Failed to unsubscribe from browser notifications:', error);
        }
    }

    async sendTestNotification() {
        try {
            // First, check if we're subscribed
            if (!this.isSubscribed) {
                const shouldSubscribe = confirm('You need to subscribe to browser notifications first. Subscribe now?');
                if (shouldSubscribe) {
                    await this.subscribe();
                    // Give a moment for subscription to complete
                    await new Promise(resolve => setTimeout(resolve, 1000));
                } else {
                    return;
                }
            }

            const response = await fetch('/test-browser-notification', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                }
            });

            if (!response.ok) {
                if (response.status === 404) {
                    // No subscriptions found on server - try subscribing
                    alert('No browser subscriptions found. Subscribing now...');
                    await this.subscribe();
                    return;
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            alert(result.message);
            console.log('Test notification result:', result);
        } catch (error) {
            console.error('Failed to send test notification:', error);
            alert(`Failed to send test notification: ${error.message}`);
        }
    }




    urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, '+')
            .replace(/_/g, '/');

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    async clearExistingSubscription() {
        /**
         * Clear any existing push subscription that might conflict with our VAPID keys
         */
        try {
            const existingSubscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
            
            if (existingSubscription) {
                console.log('Found existing subscription, unsubscribing...');
                await existingSubscription.unsubscribe();
                console.log('Successfully cleared existing subscription');
            }
        } catch (error) {
            console.warn('Failed to clear existing subscription:', error);
            // Don't throw - this is just cleanup
        }
    }

    showSubscriptionConflictDialog(error) {
        /**
         * Show user-friendly dialog for subscription conflicts
         */
        const message = `Browser notifications are already set up for a different changedetection.io instance or with different settings.

To fix this:
1. Clear your existing subscription 
2. Try subscribing again

Would you like to automatically clear the old subscription and retry?`;

        if (confirm(message)) {
            this.clearExistingSubscription().then(() => {
                // Retry subscription after clearing
                setTimeout(() => {
                    this.subscribe();
                }, 500);
            });
        } else {
            alert('To use browser notifications, please manually clear your browser notifications for this site in browser settings, then try again.');
        }
    }

    async clearAllNotifications() {
        /**
         * Clear all browser notification subscriptions (admin function)
         */
        try {
            // Clear service worker subscription
            const existingSubscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
            if (existingSubscription) {
                await existingSubscription.unsubscribe();
            }

            // Update status
            this.isSubscribed = false;
            
            console.log('All notifications cleared');
            alert('All browser notifications have been cleared. You can now subscribe again.');
            
        } catch (error) {
            console.error('Failed to clear all notifications:', error);
            alert('Failed to clear notifications. Please manually clear them in browser settings.');
        }
    }

}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.browserNotifications = new BrowserNotifications();
    });
} else {
    window.browserNotifications = new BrowserNotifications();
}