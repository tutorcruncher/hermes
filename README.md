# TC - Hermes

Hermes is our sales system that manages the connection between TutorCruncher (the system), the callbooker on our 
website, and Pipedrive (our current sales CRM).

This system is built using TortoiseORM and FastAPI.

## Terms

- **Company** - A business that is a potential/current customer of TutorCruncher. Called an `Organisation` in Pipedrive.
- **Contact** - Someone who works for the Company. Called a `Person` in Pipedrive.
- **Pipeline** - The sales pipelines
- **Stage** - The stages of the pipelines
- **Deal** - A potential sale with a Company. Called the same in Pipedrive
- **Meeting** - A meeting with a Contact. Called an `Activity` in Pipedrive

## Project structure

This project consists of 4 apps:
- `admin`: Used as an admin interface to deal with configuration
- `callbooker`: Deals with callbacks and availability from the callbooker on the website
- `pipedrive`: Deals with callbacks and data synch to Pipedrive
- `tc2`: Deals with callbacks and data synch to Pipedrive

## Actions

Listed here are the various actions all they are supposed to do in Hermes so that everything is properly synced.
`[Task]` means that we do that logic using FastAPI's background tasks.

### From TutorCruncher (the system)

TC will send webhooks whenever something happens to the Client/Invoice objects. We catch those webhooks and do logic 
based off them. The Client object will have ServiceRecipients attached to them and we create Contacts from them.

We only want to do something in Hermes if the Client/Invoice relate to new sales.

When an Invoice is created/update, or a Client is created/updated in TutorCruncher:
- Hermes - Create/update a new Company
- Hermes - Create/update a new Contact
- Hermes - Create/update a new Deal
- Pipedrive - Create/update a new Organisation `[Task]`
- Pipedrive - Create/update a new Person `[Task]`
- Pipedrive - Create a new Deal `[Task]`

When a Client is deleted in TutorCruncher:
- Hermes - Delete the Company
- Hermes - Delete the Contact

### From the website callbooker

The callbooker is a form on our website that allows people to book a call with us. It will send a webhook to Hermes 
when someone fills it out. There are two types of calls, sales or support. Sales calls should create companies/deals
in Pipedrive, support calls should not.

When a sales call is booked
- Hermes - Create/update a new Company
- Hermes - Create/update a new Contact
- Hermes - Create/update a new Meeting
- Hermes - Create/update a new Deal
- Pipedrive - Create/update a new Organisation `[Task]`
- Pipedrive - Create/update a new Person `[Task]`
- Pipedrive - Create a new Deal `[Task]`
- Pipedrive - Create a new Activity `[Task]`

When a support call is booked
- Hermes - Create/update a new Company
- Hermes - Create/update a new Contact
- Hermes - Create/update a new Meeting
- Pipedrive - Create/update a new Contact `[Task]`
- Pipedrive - Create a new Activity `[Task]`

### From Pipedrive

Pipedrive will send webhooks whenever something happens, we catch the ones that pertain to Organisations, Persons, 
Pipelines and Stages. We do logic based off them.

When a new Organisation is created/updated in Pipedrive:
- Hermes - Create/update a new Company
- TC2 - Update the Client `[Task]`

When a new Person is created/updated in Pipedrive:
- Hermes - Create/update a new Contact

When a new Pipeline is created/updated in Pipedrive:
- Hermes - Create/update a new Pipeline

When a new Stage is created/updated in Pipedrive:
- Hermes - Create/update a new Stage


## TODOs:

* [ ] Callbooker dev
* [ ] TC2 dev
* [ ] Should marking a customer as a NARC deleted them from Hermes and Pipedrive? Think so.
* [ ] Check PD callbacks include custom fields
* [ ] Test live
