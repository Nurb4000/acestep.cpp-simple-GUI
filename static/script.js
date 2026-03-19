// script.js
$(document).ready(function() {
    let currentBaseFilename = '';
    let currentUseLLM = false;
    let currentUseRefAudio = false;

    $('#musicForm').on('submit', function(e) {
        e.preventDefault();
        $('#results').addClass('hidden');
        $('#error').addClass('hidden').html('');
        $('#loading').removeClass('hidden');
        $('#generateBtn').prop('disabled', true);

        const formData = new FormData(this);
        const useLLM = $('#use_llm').is(':checked');
        const useRefAudio = $('#use_reference_audio').is(':checked');

        // Explicitly set flags
        formData.set('use_llm', useLLM ? 'true' : 'false');
        formData.set('use_reference_audio', useRefAudio ? 'true' : 'false');

        // Ensure caption is always included (even if empty)
        const caption = $('#caption').val();
        formData.set('caption', caption);  // Explicitly set

        // Append file only if reference audio is selected AND a file exists
        const fileInput = document.getElementById('reference_audio');
        if (useRefAudio && fileInput.files.length > 0) {
            const file = fileInput.files[0];
            formData.append('reference_audio', file);
            console.log("Appended reference audio to form:", file.name);
        } else if (useRefAudio && fileInput.files.length === 0) {
            showError("Reference audio is selected but no file was chosen.");
            $('#loading').addClass('hidden');
            $('#generateBtn').prop('disabled', false);
            return;
        }

        // Log what’s being sent
        for (let [key, value] of formData.entries()) {
            console.log(`${key}:`, value);
        }

        $.ajax({
            url: '/generate',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(response) {
                console.log("Server response:", response);
                if (response.status === 'success') {
                    currentBaseFilename = response.base_filename;
                    currentUseLLM = response.use_llm || false;
                    currentUseRefAudio = response.use_reference_audio || false;

                    const audioPlayer = `
                        <audio controls class="w-full">
                            <source src="${response.wav_url}" type="audio/wav">
                            Your browser does not support the audio element.
                        </audio>
                    `;
                    $('#audioPlayer').html(audioPlayer);

                    $('#downloadBtn').off('click').on('click', function() {
                        const params = new URLSearchParams();
                        params.append('use_llm', currentUseLLM);
                        params.append('use_reference_audio', currentUseRefAudio);
                        window.location.href = `${response.download_url}?${params.toString()}`;
                    });

                    $('#results').removeClass('hidden');
                } else {
                    showError(response.message || 'An error occurred during generation.');
                }
            },
            error: function(xhr, status, error) {
                let errorMsg = 'An error occurred while communicating with the server.';
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    errorMsg = xhr.responseJSON.message;
                    if (xhr.responseJSON.details) {
                        errorMsg += `<br><small>${xhr.responseJSON.details}</small>`;
                    }
                } else if (xhr.responseText) {
                    try {
                        const errorResponse = JSON.parse(xhr.responseText);
                        errorMsg = errorResponse.message || errorMsg;
                        if (errorResponse.details) {
                            errorMsg += `<br><small>${errorResponse.details}</small>`;
                        }
                    } catch (e) {
                        errorMsg += `<br><small>${xhr.responseText}</small>`;
                    }
                }
                showError(errorMsg);
                console.error('Error details:', xhr.responseText);
            },
            complete: function() {
                $('#loading').addClass('hidden');
                $('#generateBtn').prop('disabled', false);
            }
        });
    });

    $('#newGenerationBtn').on('click', function() {
        $('#results').addClass('hidden');
        $('#musicForm')[0].reset();
        currentBaseFilename = '';
        currentUseLLM = false;
        currentUseRefAudio = false;
    });

    function showError(message) {
        const errorDiv = $('#error');
        errorDiv.html(message).removeClass('hidden');
        $('html, body').animate({
            scrollTop: errorDiv.offset().top - 100
        }, 500);
    }
});
