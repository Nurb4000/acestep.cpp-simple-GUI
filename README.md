# acestep.cpp-simple-GUI

Another super simple web interface for something because im too lazy to type.
This simply creates the json and passes it into the command line to run the generations. It presents all the variables to you, with defaults. Also lets you select with LLM or without.  Has a preview feature, and will let you download the jsons and output as a zip.


To get started, either compile or download binaries for you platform from https://github.com/ServeurpersoCom/acestep.cpp and drop them into the bin folder.

The get the minimum required ggufs and drop them into the models folder. ( also documented on the above repo ):   acestep-5Hz-lm-4B-Q8_0.gguf, acestep-v15-turbo-Q8_0.gguf, Qwen3-Embedding-0.6B-Q8_0.gguf, vae-BF16.gguf.

Be sure to grab dependencies from the requirements.txt file, which is minimal as always - flask, pygame, python-dotenv

And once again, obligatory screenshot:

<img width="1015" height="921" alt="image" src="https://github.com/user-attachments/assets/a72c7b31-c72b-49f5-a965-6fbb7b2e1050" />

