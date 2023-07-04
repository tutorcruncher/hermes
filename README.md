# TC - Hermes

Hermes is considered the herald of the gods. He is also considered the protector of human heralds, travellers, thieves, merchants, and orators. He is able to move quickly and freely between the worlds of the mortal and the divine, aided by his winged sandals. Hermes is regarded as "the divine trickster"

![image](https://user-images.githubusercontent.com/61923868/187387693-6169bb33-618a-43d0-8e66-b98ce8a15c1d.png)

In the likeness of the God Hermes has been named after it works accross multiple worlds integrating all angles of our sales pipeline and distributing messages to our other services. Equally our Hermes is consistently playing the trickster with janky timezone code and an imperfect Hubspot integration. Good Luck in here.


### Local testing
- Set up ngrok with ```ngrok http 8000```
- Export relevant Hubspot variables in env. If using Google Cal there is a lot, need to check heroku.
- Run both ```foxglove web``` and ```foxglove worker```
- Run tests using ```pytest```
- If testing Callbooker, replace https://tutorcruncher.com with given ngrok address. Run tc.com locally with ```harrier dev --port 8001``` allow http://localhost:8001 and http://localhost for CORS middleware in main.py
  

