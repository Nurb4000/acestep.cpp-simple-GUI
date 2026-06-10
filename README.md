# acestep.cpp-simple-GUI

Another super simple web interface for something because im too lazy to type.

This simply creates the json for you, and passes it into the command line to run the generations. With a super simple GUI.

Current features:

- It presents all the important ( to me anyway ) variables, with what i feel are rational defaults. 
- Lets you process your prompt using the OEM LLM, and have it fill in the results for you to edit, or totally dismss and try again before actual music generation.
- Supports uploading a reference and source audio track.
- Audio preview feature, and will let you download the jsons, output, reference and source, as a zip if you want to keep the set.   
- Supports selecting the synth model ( the list is hard coded but easily added/changed ). 
- Rcentely added cover task features. 
- You can also now save the current settings as an an arbitrary json file for safe keeping without having to call the generate or llm-enhance,or llm-analyze as well as load it back in. 
- Auto cleanup is back. Each new generation should clear out files from previous ones.
- Batch generation has been added. This is an external batch process and not the one built into the backend, so you can have it run as many as you want, regardless of your hardware. All you need is patience.  It takes all your current parameters, and randomizes the seed each run.  At the end, it will automatically create and download the zip, which will include all the related jsons, reference files, source files, and results. So it could get big. Note that this auto-zip may change later if we enhance the audio preview feature to support selection in this case of multiple files.
- For those of us with older GPUs that produce silence, there is now an option in the GUI for this, no need to pass a paramater now. just selct "-clamp-fp16" in the "addtional args" area before generation.
- Adapter support in generation.  ( like LORAs )
- Allows creating the random seed from the UI, not relying on the generation LLM, but you can still pass -1 if you like for the LLM to do it for you. But it wont be stored in the json.
- And, tho im not real fond of its accuracy on actual lyrics, "llm-Analyze" option is available, to feed the reference audio into the OEM llm ( using the cli defaults ). It will feed the results of its analysis back into the GUI for review/edit/removal/redo, much like LLM-Enhance does, only this time its just listening to the audio track, and not the text you have entered. It does an ok job on structure, so figured it might be of use to have it.


To get started, either compile or download binaries for your platform from https://github.com/ServeurpersoCom/acestep.cpp and drop them into the bin folder.

Then get the minimum required ggufs and drop them into the models folder. ( also documented on the above repo ):   acestep-5Hz-lm-4B-Q8_0.gguf, acestep-v15-turbo-Q8_0.gguf, Qwen3-Embedding-0.6B-Q8_0.gguf, vae-BF16.gguf. I suggest you also get XL versions, but its not required. ( but watch it as the defaut now is XL )

Be sure to grab python dependencies from the requirements.txt file, which is minimal as always - in this case just flask and python-dotenv

And once again, obligatory ( updated for current featureset ) screenshot:

<img width="776" height="808" alt="image" src="https://github.com/user-attachments/assets/7a305696-c650-464f-bd5b-37c69d5c1257" />
















