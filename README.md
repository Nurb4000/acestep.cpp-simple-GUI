# acestep.cpp-simple-GUI

** Updated to fix breaking changes upstream with CLI options. Should be working now **


Another super simple web interface for something because im too lazy to type.

This simply creates the json for you, and passes it into the command line to run the generations. It presents all the variables to you, with defaults. It also now lets you process your prompt using the OEM LLM, and have it fill in the results for you to edit, or totally dismss and try again before actual music generation.  Has a audio preview feature, and will let you download the jsons and output as a zip.   It also now supports uploading a reference audio track. It now supports selecting the DIT model ( of the 3 out of box ones ). Also added some cover features as well. You can also now save json as an arbirtray file without having to call the generate or llm-enhance, as well as load it back in. Exporting to zip includes any cover files used.


To get started, either compile or download binaries for your platform from https://github.com/ServeurpersoCom/acestep.cpp or https://github.com/ace-step/acestep.cpp and drop them into the bin folder.

Then get the minimum required ggufs and drop them into the models folder. ( also documented on the above repo ):   acestep-5Hz-lm-4B-Q8_0.gguf, acestep-v15-turbo-Q8_0.gguf, Qwen3-Embedding-0.6B-Q8_0.gguf, vae-BF16.gguf.  Suggest you also get XL versions, but its not required.

Be sure to grab dependencies from the requirements.txt file, which is minimal as always - in this case just flask and python-dotenv

For those of us with older GPUs that produce silence, there is now an option in the GUI for this, no need to pass a paramater now. just selct "-clamp-fp16" in the "addtional args" area before generation.

And once again, obligatory ( updated for current featureset ) screenshot:

<img width="751" height="813" alt="image" src="https://github.com/user-attachments/assets/09451eef-3b6f-4412-87b3-de2be85184e1" />










