function analyzeMedia() {
    const fileInput = document.getElementById('mediaInput');
    const file = fileInput.files[0];

    if (!file) {
        alert('Please select a file first.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    fetch('/detect', {
        method: 'POST',
        body: formData
    })
    response => response.json())
    .then(data => {
        const resultDiv = document.getElementById('result');
        const statusText = document.getElementById('statusText');
        const confidenceText = document.getElementById('confidenceText');

        resultDiv.classList.remove('hidden');

        if (data.is_deepfake) {
            statusText.textContent = 'Warning: This media is likely a deepfake.';
            statusText.style.color = '#cf6679';
        } else {
            statusText.textContent = 'This media appears to be authentic.';
            statusText.style.color = '#03dac6';
        }
        confidenceText.textContent = `Confidence: ${(data.confidence * 100).toFixed(2)}%`;
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred during analysis.');
    });
}
