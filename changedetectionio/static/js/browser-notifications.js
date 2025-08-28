/**
 * changedetection.io Browser Push Notifications
 * Handles service worker registration, push subscription management, and notification permissions
 */

class BrowserNotifications {
    constructor() {
        this.serviceWorkerRegistration = null;
        this.vapidPublicKey = null;
        this.subscriptions = new Map(); // keyword -> subscription
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
            
            // Load existing subscriptions
            await this.loadExistingSubscriptions();
            
            // Handle auto-subscription from form submission
            await this.handleAutoSubscription();
            
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
            const response = await fetch('/api/v1/browser-notifications/vapid-public-key');
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
                // Check for pending auto-subscriptions
                this.handleAutoSubscription();
            } else {
                console.log('Notification permission denied');
            }
        } catch (error) {
            console.error('Error requesting notification permission:', error);
        }
    }

    async subscribeToKeyword(keyword = null) {
        if (Notification.permission !== 'granted') {
            alert('Please enable notifications first');
            return;
        }

        if (!keyword) {
            keyword = document.querySelector('#notification-keyword-input')?.value?.trim() || 'default';
        }

        if (!keyword) {
            alert('Please enter a keyword');
            return;
        }

        try {
            // Check if already subscribed to this keyword
            if (this.subscriptions.has(keyword)) {
                console.log(`Already subscribed to keyword: ${keyword}`);
                return;
            }

            // First, try to clear any existing subscription with different keys
            await this.clearExistingSubscription();

            // Create push subscription
            const subscription = await this.serviceWorkerRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: this.urlBase64ToUint8Array(this.vapidPublicKey)
            });

            // Send subscription to server
            const response = await fetch('/api/v1/browser-notifications/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                },
                body: JSON.stringify({
                    keyword: keyword,
                    subscription: subscription.toJSON()
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // Store subscription locally
            this.subscriptions.set(keyword, subscription);
            
            // Update UI
            this.updateSubscriptionsList();
            
            console.log(`Successfully subscribed to keyword: ${keyword}`);
            
            // Clear input
            const input = document.querySelector('#notification-keyword-input');
            if (input) input.value = '';

        } catch (error) {
            console.error(`Failed to subscribe to keyword ${keyword}:`, error);
            
            // Show user-friendly error message
            if (error.message.includes('different applicationServerKey')) {
                this.showSubscriptionConflictDialog(keyword, error);
            } else {
                alert(`Failed to subscribe: ${error.message}`);
            }
        }
    }

    async unsubscribeFromKeyword(keyword) {
        try {
            const subscription = this.subscriptions.get(keyword);
            if (!subscription) return;

            // Unsubscribe from server
            const response = await fetch('/api/v1/browser-notifications/unsubscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                },
                body: JSON.stringify({
                    keyword: keyword,
                    subscription: subscription.toJSON()
                })
            });

            if (!response.ok) {
                console.warn(`Server unsubscribe failed: ${response.status}`);
            }

            // Remove from local storage
            this.subscriptions.delete(keyword);
            
            // Update UI
            this.updateSubscriptionsList();
            
            console.log(`Unsubscribed from keyword: ${keyword}`);

        } catch (error) {
            console.error(`Failed to unsubscribe from keyword ${keyword}:`, error);
        }
    }

    updateSubscriptionsList() {
        const listElement = document.querySelector('#subscriptions-list');
        if (!listElement) return;

        listElement.innerHTML = '';

        if (this.subscriptions.size === 0) {
            listElement.innerHTML = '<li>No active subscriptions</li>';
            return;
        }

        for (const [keyword] of this.subscriptions) {
            const listItem = document.createElement('li');
            listItem.innerHTML = `
                <span>browser://${keyword}</span>
                <button type="button" class="btn btn-sm btn-danger" onclick="browserNotifications.unsubscribeFromKeyword('${keyword}')" style="margin-left: 1em;">
                    Unsubscribe
                </button>
            `;
            listElement.appendChild(listItem);
        }
    }

    async loadExistingSubscriptions() {
        try {
            const response = await fetch('/api/v1/browser-notifications/subscriptions');
            if (response.ok) {
                const data = await response.json();
                // Note: This would require server-side implementation to track subscriptions per browser
                // For now, we'll just check what the browser knows about
            }
        } catch (error) {
            console.log('No existing subscriptions found');
        }
    }

    async sendTestNotification() {
        try {
            // Get available channels from the form field
            const channelsField = document.querySelector('textarea[name*="browser_notification_channels"]');
            const channels = channelsField?.value ? channelsField.value.split('\n').filter(c => c.trim()) : [];
            const keyword = channels.length > 0 ? channels[0] : 'default';
            
            const response = await fetch('/api/v1/browser-notifications/test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                },
                body: JSON.stringify({
                    keyword: keyword,
                    title: 'Test Notification',
                    body: `This is a test notification for channel: ${keyword}`
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            alert(`Test notification sent successfully to ${result.sent_count} subscriber(s)`);
            console.log('Test notification sent');
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

    showSubscriptionConflictDialog(keyword, error) {
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
                    this.subscribeToKeyword(keyword);
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

            // Clear local storage
            this.subscriptions.clear();
            
            // Update UI
            this.updateSubscriptionsList();
            
            console.log('All notifications cleared');
            alert('All browser notifications have been cleared. You can now subscribe again.');
            
        } catch (error) {
            console.error('Failed to clear all notifications:', error);
            alert('Failed to clear notifications. Please manually clear them in browser settings.');
        }
    }

    async handleAutoSubscription() {
        // Handle auto-subscription for keywords detected from browser:// URLs
        try {
            // Check if there are pending keywords from form submission
            const response = await fetch('/api/v1/browser-notifications/pending-keywords', {
                headers: {
                    'X-CSRFToken': document.querySelector('input[name=csrf_token]')?.value
                }
            });
            
            if (!response.ok) {
                return; // No pending keywords or endpoint not available
            }
            
            const data = await response.json();
            if (!data.keywords || data.keywords.length === 0) {
                return;
            }
            
            // Check if notifications are already enabled
            if (Notification.permission === 'granted') {
                // Auto-subscribe to all pending keywords
                for (const keyword of data.keywords) {
                    try {
                        await this.subscribeToKeyword(keyword);
                        console.log(`Auto-subscribed to browser notifications for: ${keyword}`);
                    } catch (error) {
                        console.warn(`Failed to auto-subscribe to ${keyword}:`, error);
                    }
                }
            } else {
                // Show notification to enable browser notifications for detected keywords
                this.showAutoSubscriptionPrompt(data.keywords);
            }
            
        } catch (error) {
            console.log('No auto-subscription needed or failed to check:', error);
        }
    }
    
    showAutoSubscriptionPrompt(keywords) {
        // Show a prompt to enable notifications for detected browser:// URLs
        const keywordList = keywords.join(', ');
        const message = `Browser notification channels detected: ${keywordList}\n\nWould you like to enable browser notifications for these channels?`;
        
        if (confirm(message)) {
            this.requestNotificationPermission().then(() => {
                // After permission is granted, subscribe to all keywords
                keywords.forEach(keyword => {
                    this.subscribeToKeyword(keyword);
                });
            });
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