/**
 * المستشار القانوني السوري — main.js
 */
'use strict';

// ===== Toast Notifications =====
function showToast(message, type = 'default', duration = 3500) {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(20px)'; toast.style.transition = 'all 0.3s'; setTimeout(() => toast.remove(), 300); }, duration);
}

// ===== User Dropdown (click support for mobile) =====
document.addEventListener('DOMContentLoaded', () => {
    const userMenu = document.querySelector('.user-menu');
    if (userMenu) {
        const btn = userMenu.querySelector('.user-btn');
        const dropdown = userMenu.querySelector('.user-dropdown');
        if (btn && dropdown) {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = dropdown.style.display === 'block';
                dropdown.style.display = isOpen ? '' : 'block';
            });
            document.addEventListener('click', () => { if (dropdown) dropdown.style.display = ''; });
        }
    }

    // Auto-dismiss alerts
    document.querySelectorAll('.alert').forEach(alert => {
        setTimeout(() => { alert.style.opacity = '0'; alert.style.transition = 'opacity 0.4s'; setTimeout(() => alert.remove(), 400); }, 5000);
    });
});

// ===== Confirm Dialog Helper =====
function confirmAction(message, callback) {
    if (window.confirm(message)) callback();
}

// ===== CSRF Token Helper =====
function getCSRF() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
           document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1] || '';
}

// ===== Quick Verify Lawyer (for admin) =====
async function verifyLawyer(id, action) {
    try {
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCSRF());
        formData.append('action', action);
        const res = await fetch(`/admin-panel/lawyers/${id}/verify/`, {method:'POST', body:formData, headers:{'X-CSRFToken':getCSRF()}});
        const data = await res.json();
        if (data.success) {
            showToast(action === 'verify' ? '✅ تم توثيق المحامي' : '⚠️ تم إلغاء التوثيق', action === 'verify' ? 'success' : 'error');
            setTimeout(() => location.reload(), 1200);
        }
    } catch (e) { showToast('❌ حدث خطأ', 'error'); }
}

// ===== Textarea Auto Resize =====
document.addEventListener('input', (e) => {
    if (e.target.tagName === 'TEXTAREA' && e.target.dataset.autoResize) {
        e.target.style.height = 'auto';
        e.target.style.height = e.target.scrollHeight + 'px';
    }
});

// ===== Rating Stars =====
function initRatingStars() {
    document.querySelectorAll('.rating-input').forEach(container => {
        const stars = container.querySelectorAll('.rating-star');
        const input = container.querySelector('input[type="hidden"]');
        stars.forEach((star, i) => {
            star.addEventListener('mouseover', () => { stars.forEach((s, j) => s.classList.toggle('hover', j <= i)); });
            star.addEventListener('mouseleave', () => { stars.forEach(s => s.classList.remove('hover')); });
            star.addEventListener('click', () => {
                const val = i + 1;
                input && (input.value = val);
                stars.forEach((s, j) => s.classList.toggle('selected', j < val));
            });
        });
    });
}
document.addEventListener('DOMContentLoaded', initRatingStars);