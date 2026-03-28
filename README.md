# acestep.cpp-simple-GUI


Another super simple web interface for something because im too lazy to type.

This simply creates the json for you, and passes it into the command line to run the generations. It presents all the variables to you, with defaults. It also now lets you process your prompt using the OEM LLM, and have it fill in the results for you to edit, or totally dismss and try again before actual music generation.  Has a audio preview feature, and will let you download the jsons and output as a zip.   It also now supports uploading a reference audio track. It now supports selecting the DIT model ( of the 3 out of box ones )


To get started, either compile or download binaries for your platform from https://github.com/ServeurpersoCom/acestep.cpp or https://github.com/ace-step/acestep.cpp and drop them into the bin folder.

Then get the minimum required ggufs and drop them into the models folder. ( also documented on the above repo ):   acestep-5Hz-lm-4B-Q8_0.gguf, acestep-v15-turbo-Q8_0.gguf, Qwen3-Embedding-0.6B-Q8_0.gguf, vae-BF16.gguf.

Be sure to grab dependencies from the requirements.txt file, which is minimal as always - in this case just flask and python-dotenv

For those of us with older GPUs that produce silence, use the paramater oldgpu=1 when you call the application. 

And once again, obligatory ( updated for current featureset ) screenshot:

<img width="963" height="885" alt="image" src="https://github.com/user-attachments/assets/33d7e495-2e4c-4345-94e5-80eb81124a13" />








