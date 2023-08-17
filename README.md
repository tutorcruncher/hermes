# TC - Hermes

Hermes is our sales system that manages the connection between TutorCruncher (the system), the callbooker on our 
website, and Pipedrive (our current sales CRM).

This system is built using TortoiseORM and FastAPI.

## Terms

Objects are named different things depending on which system you use:

| Hermes   | TutorCruncher | Pipedrive    | Description                                                       |
|----------|---------------|--------------|-------------------------------------------------------------------|
| Company  | Cligency      | Organisation | A business that is a potential/current customer of TutorCruncher. |
| Contact  | SR            | Person       | Someone who works for the Company.                                |
| Pipeline |               | Pipeline     | The sales pipelines                                               |
| Stage    |               | Stage        | The stages of the pipelines                                       |
| Deal     |               | Deal         | A potential sale with a Company.                                  |
| Meeting  |               | Activity     | A meeting with a Contact.                                         |

## Project structure

This project consists of 4 apps:
- `admin`: Used as an admin interface to deal with configuration
- `callbooker`: Deals with callbacks and availability from the callbooker on the website
- `pipedrive`: Deals with callbacks and data synch to Pipedrive
- `tc2`: Deals with callbacks and data synch to Pipedrive

## Actions/testing

The list of all workflows is in the workflows.md file. They need to all be tested.

### Running locally

Install the dependencies with `make install`. You may need to create the database with `make reset-db`.
Then run the server with `python -m uvicorn app.main:app --reload`

You'll be able to view the admin interface at http://localhost:8000/. To login, go to /login. You need to have an admin
already created; if you look in `utils.py` you'll see some code you can uncomment so that the admin is created when the
server starts.

## TODOs:

* [ ] Callbooker dev
* [ ] TC2 dev
* [ ] Should marking a customer as a NARC deleted them from Hermes and Pipedrive? Think so.
* [ ] If a company is changed in TC to have it's PD org ID set, then it should be linked to the company in PD
* [ ] Deal with merging Orgs/Persons.
