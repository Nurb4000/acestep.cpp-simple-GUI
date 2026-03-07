$(document).ready(function() {
    let currentBaseFilename = '';
    let currentUseLLM = false;
    
    // Handle form submission
    $('#musicForm').on('submit', function(e) {
        e.preventDefault();
        
        // Reset state
        $('#results').addClass('hidden');
        $('#error').addClass('hidden').html('');
        
        // Show loading
        $('#loading').removeClass('hidden');
        $('#generateBtn').prop('disabled', true);
        
        // Get form data
        const formData = {
            use_llm: $('#use_llm').is(':checked'),
            caption: $('#caption').val(),
            lyrics: $('#lyrics').val(),
            duration: parseFloat($('#duration').val()) || 0,
            lm_negative_prompt: $('#lm_negative_prompt').val(),
            bpm: parseInt($('#bpm').val()) || 0,
            keyscale: $('#keyscale').val(),
            timesignature: $('#timesignature').val(),
            vocal_language: $('#vocal_language').val(),
            seed: parseInt($('#seed').val()) || -1,
            lm_temperature: parseFloat($('#lm_temperature').val()) || 0.85,
            lm_cfg_scale: parseFloat($('#lm_cfg_scale').val()) || 2.0,
            lm_top_p: parseFloat($('#lm_top_p').val()) || 0.9,
            lm_top_k: parseInt($('#lm_top_k').val()) || 0,
            audio_codes: $('#audio_codes').val(),
            inference_steps: parseInt($('#inference_steps').val()) || 8,
            guidance_scale: parseFloat($('#guidance_scale').val()) || 0.0,
            shift: parseFloat($('#shift').val()) || 3.0,
            audio_cover_strength: parseFloat($('#audio_cover_strength').val()) || 0.5
        };
        
        console.log("Submitting form data:", formData);
        
        // Send request to server
        $.ajax({
            url: '/generate',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(formData),
            success: function(response) {
                console.log("Server response:", response);
                
                if (response.status === 'success') {
                    currentBaseFilename = response.base_filename;
                    currentUseLLM = response.use_llm || false;
                    
                    // Create audio player
                    const audioPlayer = `
                        <audio controls class="w-full">
                            <source src="${response.wav_url}" type="audio/wav">
                            Your browser does not support the audio element.
                        </audio>
                    `;
                    $('#audioPlayer').html(audioPlayer);
                    
                    // Set download button href with use_llm parameter
                    $('#downloadBtn').off('click').on('click', function() {
                        window.location.href = `${response.download_url}?use_llm=${currentUseLLM}`;
                    });
                    
                    // Show results
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
    
    // Handle new generation button
    $('#newGenerationBtn').on('click', function() {
        $('#results').addClass('hidden');
        // Reset form to default values
        $('#musicForm')[0].reset();
    });
    
    function showError(message) {
        const errorDiv = $('#error');
        errorDiv.html(message).removeClass('hidden');
        // Scroll to error message
        $('html, body').animate({
            scrollTop: errorDiv.offset().top - 100
        }, 500);
    }
});