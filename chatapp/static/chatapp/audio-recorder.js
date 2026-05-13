/**
 * وظائف تسجيل الصوت
 */

let mediaRecorder;
let audioChunks = [];
let recordingStartTime;
let recordingTimer;
let stream;

/**
 * بدء التسجيل الصوتي
 */
async function startRecording() {
    try {
        // طلب إذن الوصول للميكروفون
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        // حفظ البيانات الصوتية
        mediaRecorder.addEventListener('dataavailable', event => {
            audioChunks.push(event.data);
        });
        
        // عند إيقاف التسجيل
        mediaRecorder.addEventListener('stop', () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            const audioFile = new File([audioBlob], `recording-${Date.now()}.webm`, { 
                type: 'audio/webm' 
            });
            
            // إضافة الملف للنموذج
            const fileInput = document.getElementById('audio-file-input');
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(audioFile);
            fileInput.files = dataTransfer.files;
            
            // عرض مشغل الصوت
            const preview = document.getElementById('audio-preview');
            const player = document.getElementById('audio-player');
            if (preview && player) {
                const url = URL.createObjectURL(audioBlob);
                player.src = url;
                preview.style.display = 'block';
            }
            
            // إيقاف المؤشر
            hideRecordingIndicator();
            
            // إيقاف Stream
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
            }
        });
        
        // بدء التسجيل
        mediaRecorder.start();
        
        // عرض مؤشر التسجيل
        showRecordingIndicator();
        
    } catch (error) {
        console.error('Error accessing microphone:', error);
        alert('فشل الوصول إلى الميكروفون. تأكد من منح الإذن.');
    }
}

/**
 * إيقاف التسجيل
 */
function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
    }
}

/**
 * عرض مؤشر التسجيل
 */
function showRecordingIndicator() {
    const indicator = document.getElementById('recording-indicator');
    const recordBtn = document.getElementById('record-btn');
    
    if (indicator) {
        indicator.style.display = 'flex';
    }
    
    if (recordBtn) {
        recordBtn.disabled = true;
        recordBtn.style.opacity = '0.5';
    }
    
    // بدء العداد
    recordingStartTime = Date.now();
    recordingTimer = setInterval(updateRecordingTime, 1000);
}

/**
 * إخفاء مؤشر التسجيل
 */
function hideRecordingIndicator() {
    const indicator = document.getElementById('recording-indicator');
    const recordBtn = document.getElementById('record-btn');
    
    if (indicator) {
        indicator.style.display = 'none';
    }
    
    if (recordBtn) {
        recordBtn.disabled = false;
        recordBtn.style.opacity = '1';
    }
    
    // إيقاف العداد
    if (recordingTimer) {
        clearInterval(recordingTimer);
    }
}

/**
 * تحديث وقت التسجيل
 */
function updateRecordingTime() {
    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
    const minutes = Math.floor(elapsed / 60);
    const seconds = elapsed % 60;
    
    const timeDisplay = document.getElementById('recording-time');
    if (timeDisplay) {
        timeDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
}

/**
 * التحقق من دعم المتصفح
 */
function checkAudioSupport() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn('Audio recording not supported in this browser');
        return false;
    }
    return true;
}

// التحقق من الدعم عند تحميل الصفحة
document.addEventListener('DOMContentLoaded', function() {
    if (!checkAudioSupport()) {
        const recordBtn = document.getElementById('record-btn');
        if (recordBtn) {
            recordBtn.disabled = true;
            recordBtn.title = 'المتصفح لا يدعم تسجيل الصوت';
        }
    }
});