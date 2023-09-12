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

Client?

## Project structure

This project consists of 4 apps:
- `admin`: Used as an admin interface to deal with configuration
- `callbooker`: Deals with callbacks and availability from the callbooker on the website
- `pipedrive`: Deals with callbacks and data synch to Pipedrive
- `tc2`: Deals with callbacks and data synch to Pipedrive

## Actions/testing

The list of all workflows is in the workflows.md file. They need to all be tested.

### Running locally

#### Ngrok:

HINT: if you create a account with ngrok, it will give you a static url that you can use for the webhooks, that will never expire ;)

run ngrok on port 8000

`ngrok http --${your ngrok domain} 8000`

#### Hermes:

Install the dependencies with `make install`. You may need to create the database with `make reset-db`.
Then run the server with `python -m uvicorn app.main:app --reload`

You'll be able to view the admin interface at http://localhost:8000/. To login, go to /login. You need to have an admin
already created; if you look in `utils.py` you'll see some code you can uncomment so that the admin is created when the
server starts.

set `.env` vars:
```
# First Run
# tests will fail if this is set to True, make sure to make reset-db before running tests
CREATE_TESTING_ADMIN=False
tc2_admin_id=66
pd_owner_id=15708604


# TC2
tc2_api_key=
tc2_base_url='http://localhost:5000'

# Pipedrive
pd_api_key=
pd_base_url='https://seb-sandbox2.pipedrive.com'


```

##### Config

Edit Hermes config in the admin interface:
- Set Price Plan Pipelines to their associated Hermes Pipeline ID
- Set Pipeline `dft_entry_pipeline_state` (warning, dropdown is not filtered by pipeline)
Create Admin

#### TC2:

Run TC2 (`hermesv2` branch) on port 5000

Add these custom fields to meta Cligency:
```
pipedrive_url : str
pipedrive_id : number
pipedrive_deal_stage : str
pipedrive_pipeline : str
```

Add API Integration to META:
- Name: `Hermes`
- URL: `https://${your ngrok domain}/tc2/callback`

Create a Meta Admin:
check `Account Managers` and `is support person`, `is sales person`

#### Pipedrive:

Create a pipedrive sandbox account.
Navigate to Profile > Tools and apps > Webhooks > Create new webhook:

- Event action: `*`

- Event object: `*`

- Endpoint URL: `https://${your ngrok domain}/pipedrive/callback`

- HTTP Auth: `None`

Add these Custom Fields to the Organisation:
```
website
paid_invoice_count : 
has_booked_call
has_signed_up
tc2_status
tc2_cligency_url
```

Get your Pipedrive Owner ID:
- Navigate to ... > User Overview > select your user
- Copy the number at the end of the URL

##### Setup Pipelines

Create a pipeline for each of the following:
- `PAYG`
- `STARTUP`
- `ENTERPRISE`

#### Callbooker:
- set `DEV_MODE=True` in `.env`
- set `G_PRIVATE_KEY` in `.env` to the private key of the google service account
- set `G_PRIVATE_KEY_ID` in `.env` to the private key id of the google service account
- ensure admin has a matching email address to the one in the sales or support team (i.e fionn@tutorcruncher.com)

## TODOs:

* [ ] Callbooker dev
* [ ] TC2 dev
* [ ] Should marking a customer as a NARC deleted them from Hermes and Pipedrive? Think so.
* [ ] If a company is changed in TC to have it's PD org ID set, then it should be linked to the company in PD
* [ ] Deal with merging Orgs/Persons.
* [ ] If Companies are made in Pipedrive, they should be created in TC ? 
