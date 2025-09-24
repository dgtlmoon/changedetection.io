// changedetection.io Service Worker for Browser Push Notifications

self.addEventListener('install', function(event) {
    console.log('Service Worker installing');
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    console.log('Service Worker activating');
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function(event) {
    console.log('Push message received', event);
    
    let notificationData = {
        title: 'changedetection.io',
        body: 'A watched page has changed',
        icon: '/static/favicons/favicon-32x32.png',
        badge: '/static/favicons/favicon-32x32.png',
        tag: 'changedetection-notification',
        requireInteraction: false,
        timestamp: Date.now()
    };
    
    // Parse push data if available
    if (event.data) {
        try {
            const pushData = event.data.json();
            notificationData = {
                ...notificationData,
                ...pushData
            };
        } catch (e) {
            console.warn('Failed to parse push data:', e);
            notificationData.body = event.data.text() || notificationData.body;
        }
    }
    
    const promiseChain = self.registration.showNotification(
        notificationData.title,
        {
            body: notificationData.body,
            icon: notificationData.icon,
            badge: notificationData.badge,
            tag: notificationData.tag,
            requireInteraction: notificationData.requireInteraction,
            timestamp: notificationData.timestamp,
            data: {
                url: notificationData.url || '/',
                timestamp: notificationData.timestamp
            }
        }
    );
    
    event.waitUntil(promiseChain);
});

self.addEventListener('notificationclick', function(event) {
    console.log('Notification clicked', event);
    
    event.notification.close();
    
    const targetUrl = event.notification.data?.url || '/';
    
    event.waitUntil(
        clients.matchAll().then(function(clientList) {
            // Check if there's already a window/tab open with our app
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            // If no existing window, open a new one
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

self.addEventListener('notificationclose', function(event) {
    console.log('Notification closed', event);
});

// Handle messages from the main thread
self.addEventListener('message', function(event) {
    console.log('Service Worker received message:', event.data);
    
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});