# TC - Hermes

<img src="https://i.ibb.co/crgkVkS/ferb0000-Hermes-the-messenger-god-if-he-lived-in-the-21st-centu-baa1282d-8782-4983-9f81-b0406eb4abbd.png" width="500">

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

#### Ngrok:
We use ngrok to expose our local hermes server to the internet, so that we can receive webhooks from Pipedrive and TC2.

HINT: if you create a account with ngrok, it will give you a static url that you can use for the webhooks, that will never expire ;)

run ngrok on port 8000

`ngrok http --${your ngrok domain} 8000`

use the given url as the webhook url in pipedrive and tc2

#### Hermes:

Install the dependencies with `make install`. 
You may need to create the database with `make reset-db`.

The first time you run the server, you'll need to create an admin user.
run `export CREATE_TESTING_ADMIN=True` in terminal.

Then run the server with `python -m uvicorn app.main:app --reload`

You'll be able to view the admin interface at http://localhost:8000/. 
To login, go to /login. You need to have an admin already created;


[//]: # (Therefore set `CREATE_TESTING_ADMIN=True` in `.env` and run the server once.)
need to check how this effects tests
[//]: # (Then set `CREATE_TESTING_ADMIN=False` and run the server again.)

set `.env` vars:
```
# First Run
tc2_admin_id=${tc meta admin id}
pd_owner_id=${pipedrive owner id}

# TC2
tc2_api_key=${tc2 api integration private key}
tc2_base_url='http://localhost:5000'

# Pipedrive
pd_api_key=${pipedrive api key} # can be found in pipedrive > settings > personal preferences > api
pd_base_url='https://seb-sandbox2.pipedrive.com'

```
- `tc2_admin_id` is the id of the admin in TC2 that will be used to create the Cligency
- `pd_owner_id` is the id of the user in Pipedrive that will be used to create the Deals and Activities for the Cligency
- `tc2_api_key` is the private key of the API integration in TC2
- `pd_api_key` is the api key of the user in Pipedrive


#### TC2:

Run TC2 (`hermesv2` branch) on port 5000


Add these custom fields to Meta Cligency (Client):
```
pipedrive_url : str (Long Textbox)
pipedrive_id : int (Number)
pipedrive_deal_stage : str (Long Textbox)
pipedrive_pipeline : str (Long Textbox)
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

Add these Custom Fields to the Person:
```
primary_email
address_country
```

Get your Pipedrive Owner ID:
- Navigate to ... > User Overview > select your user
- Copy the number at the end of the URL

##### Hermes Config Tab

- Navigate to the Hermes Config tab in the admin interface

Edit Hermes config in the admin interface:
- Set Price Plan Pipelines to their associated Hermes Pipeline ID i.e ()
- Set Pipeline `dft_entry_pipeline_state` (warning, dropdown is not filtered by pipeline)
Create Admin:
- Create an admin user in the admin interface
- ensure the admins email address and `tc_admin_id` match the ones in TC2

##### Setup Pipelines

Create a pipeline for each of the following:
- `PAYG`
- `STARTUP`
- `ENTERPRISE`

#### Setup Callbooker:
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
