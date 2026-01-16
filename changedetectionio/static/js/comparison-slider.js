/**
 * Interactive Image Comparison Slider
 *
 * Allows users to drag a vertical slider to reveal differences between
 * two images (before/after comparison).
 */
(function() {
    'use strict';

    function initComparisonSlider() {
        const container = document.getElementById('comparison-container');
        const slider = document.getElementById('comparison-slider');
        const afterWrapper = container ? container.querySelector('.comparison-after') : null;
        const handle = slider ? slider.querySelector('.comparison-handle') : null;

        if (!container || !slider || !afterWrapper || !handle) {
            return;
        }

        let isDragging = false;
        let isMouseOverContainer = false;
        let mouseY = 0;

        /**
         * Update handle position - follows mouse if hovering, or viewport center
         */
        function updateHandlePosition() {
            const containerRect = container.getBoundingClientRect();
            let handleTop;

            if (isMouseOverContainer) {
                // Mouse is over container - follow the mouse Y position
                handleTop = mouseY - containerRect.top;
            } else {
                // Mouse not over container - use viewport center
                const viewportCenter = window.innerHeight / 2;

                if (containerRect.top > viewportCenter) {
                    // Container is below viewport center - position handle at container top
                    handleTop = 0;
                } else if (containerRect.bottom < viewportCenter) {
                    // Container is above viewport center - position handle at container bottom
                    handleTop = containerRect.height;
                } else {
                    // Container spans viewport center - position handle at viewport center
                    handleTop = viewportCenter - containerRect.top;
                }
            }

            // Ensure handle stays within container bounds
            handleTop = Math.max(24, Math.min(handleTop, containerRect.height - 24));

            handle.style.top = handleTop + 'px';
        }

        /**
         * Track mouse position over container
         */
        function onMouseMoveContainer(e) {
            mouseY = e.clientY;
            updateHandlePosition();
        }

        /**
         * Mouse enters container
         */
        function onMouseEnter() {
            isMouseOverContainer = true;
        }

        /**
         * Mouse leaves container
         */
        function onMouseLeave() {
            isMouseOverContainer = false;
            updateHandlePosition();
        }

        /**
         * Update slider position and clip-path
         */
        function updateSlider(clientX) {
            const rect = container.getBoundingClientRect();
            const pos = Math.max(0, Math.min(clientX - rect.left, rect.width));
            const percentage = (pos / rect.width) * 100;

            slider.style.left = percentage + '%';
            afterWrapper.style.clipPath = `inset(0 0 0 ${percentage}%)`;
        }

        /**
         * Handle move events (mouse or touch)
         */
        function onMove(e) {
            if (!isDragging) return;
            e.preventDefault();

            const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
            updateSlider(clientX);
        }

        /**
         * Start dragging
         */
        function onStart(e) {
            isDragging = true;
            const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
            updateSlider(clientX);
        }

        /**
         * Stop dragging
         */
        function onEnd() {
            isDragging = false;
        }

        /**
         * Click anywhere on container to jump slider to that position
         */
        function onClick(e) {
            if (e.target !== slider && !slider.contains(e.target)) {
                const clientX = e.clientX;
                updateSlider(clientX);
            }
        }

        // Mouse events
        slider.addEventListener('mousedown', onStart);
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onEnd);

        // Touch events
        slider.addEventListener('touchstart', onStart, { passive: false });
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onEnd);

        // Click anywhere on container to move slider
        container.addEventListener('click', onClick);

        // Track mouse position over container for handle following
        container.addEventListener('mouseenter', onMouseEnter);
        container.addEventListener('mouseleave', onMouseLeave);
        container.addEventListener('mousemove', onMouseMoveContainer, { passive: true });

        // Update handle position on scroll and resize
        window.addEventListener('scroll', updateHandlePosition, { passive: true });
        window.addEventListener('resize', updateHandlePosition, { passive: true });

        // Initial position
        updateHandlePosition();

        // Cleanup on page unload
        window.addEventListener('beforeunload', function() {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onEnd);
            document.removeEventListener('touchmove', onMove);
            document.removeEventListener('touchend', onEnd);
            container.removeEventListener('mouseenter', onMouseEnter);
            container.removeEventListener('mouseleave', onMouseLeave);
            container.removeEventListener('mousemove', onMouseMoveContainer);
            window.removeEventListener('scroll', updateHandlePosition);
            window.removeEventListener('resize', updateHandlePosition);
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initComparisonSlider);
    } else {
        initComparisonSlider();
    }
})();
