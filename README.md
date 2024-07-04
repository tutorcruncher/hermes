# TC - Hermes  
  
![hermes_v2_favicon (1)](https://github.com/tutorcruncher/hermes/assets/70067036/2019e4cf-056e-4e85-9694-5fa0b76dd2a4)

  
Hermes is our sales system that manages the connection between TutorCruncher (the system), the callbooker on our   
website, and Pipedrive (our current sales CRM).  
  
This system is built using TortoiseORM and FastAPI.
  
## Glossary  
  
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
- `pipedrive`: Deals with callbacks and data sync to Pipedrive  
- `tc2`: Deals with callbacks and data sync to Pipedrive
- `hermes` : Deals with data to do with the entire Hermes system

## Running locally  

Since Hermes works with tutorcruncher.com, the TC2 system and Pipedrive, there is quite a lot to set up to get the system working:

### TC2:  - Set this up first
  
Run TC2 locally on port 5000. `python manage.py runserver 5000`
  
#### TC2 Environment Variables
```  
# Hermes
HERMES_URL = 'https://${your ngrok domain}'  
HERMES_API_KEY = ${tc2 api integration private key} # same as tc2_api_key in hermes env vars
```  

#### Create Meta Admins:  
Create 5 Admins in TC2, for each of the following:
- payg / startup sales
- enterprise sales
- support 1
- support 2
- bdr
  
#### Meta Client Custom Fields:
Navigate to System > Settings > Custom Fields > Add Custom Field
```
estimated_monthly_income: str (Short Textbox)     # estimated monthly income of the Cligency
utm_source: str (Short Textbox)                  # utm source of the Cligency
utm_campaign: str (Short Textbox)                # utm campaign of the Cligency
currency: str (Short Textbox)                    # currency of the Cligency
referer: str (Short Textbox)                     # referer of the Cligency
```
  
#### Add API Integration to META:  

Navigate to ... > Settings > API Integrations > Create API Integration

- Name: `Hermes`  
- URL: `http://localhost:8000/tc2/callback/`  

this will create a private key, copy this and set it as `tc2_api_key` in hermes env vars and `HERMES_API_KEY` in tc2 env vars.

### Pipedrive:

Pipedrive is our current sales CRM. We use it to manage our sales pipelines and deals.

Create a pipedrive sandbox account.  
Navigate to Profile > Tools and apps > Webhooks > Create 7 new webhooks:
- Event action: `*`
- Event object: `deal`, `organization`, `pipeline`, `person`, `product`, `stage`, `user`
- Endpoint URL: `https://${your ngrok domain}/pipedrive/callback/`
- HTTP Auth: `None`  
  
#### Setting the Data Fields:  
Navigate to Company Settings > Data Fields

###### Organization Default Custom Fields:

Hint: Look at Extra Tips (at the bottom of README) for a more detailed guide on how to add a new custom field to Pipedrive

```  
website  
paid_invoice_count  

[//]: # (has_booked_call  )

[//]: # (has_signed_up  )
tc2_status: Large text  
tc2_cligency_url: Large text
hermes_id: Numerical
bdr_person_id: Numerical
utm_campaign: Large text
utm_source: Large text
estimated_monthly_income: Large text
currency: Large text
support_person_id: Numerical
signup_questionnaire: Large text
website: Large text
```  
###### Person Default Custom Fields:
```
hermes_id
```
###### Deal Default Custom Fields:
```
hermes_id
```

#### Setup Pipedrive Users:

-> Navigate to Company settings > Manage users > Add User

Now we should setup a couple of users in Pipedrive:
- `payg / startup sales`
- `enterprise sales`
- `bdr`

You can use your email address for each user, i.e sebastian+pdbdrperson@tutorcruncher.com


Get your Pipedrive Owner ID for your Hermes Admins:  
- Navigate to ... -> Navigate to Company settings > Manage users > select your user  
- Copy the number at the end of the URL

  

### Hermes:

Install the dependencies with `make install`.   
You may need to create the database with `make reset-db`.  
  
Then run the server with `python -m uvicorn app.main:app --reload`  
  
You'll be able to view the admin interface at http://localhost:8000/.   

To first create an admin, go to `/init` to create an admin user.
Then go to `/login` to log in.
  
#### Hermes Environment Variables
```  
# TC2  
tc2_api_key={tc2 api integration private key}          # can be found in tc2 meta > settings > api
tc2_base_url='http://localhost:5000'                    # url of your tc2 instance
  
# Pipedrive  
pd_api_key={pipedrive api key}                         # can be found in pipedrive > settings > personal preferences > api  
pd_base_url='https://seb-sandbox2.pipedrive.com'        # your pipedrive sandbox url
```

#### Create a Hermes Admins:
Create 5 Admins in Hermes, for each of the following:
- payg / startup sales
- enterprise sales
- support 1
- support 2
- bdr

When creating the admin, ensure that the `email` matches their Google account email address, and that the `tc2_admin_id` matches the id of the admin in TC2. and that the `pd_owner_id` matches the id of the user in Pipedrive.

for support admins, set the `pd_owner_id` to 0


### Custom Fields:
Custom fields are used to transfer additional data between TC2 and Pipedrive.
'Custom Fields' are referred to as 'Data Fields' in Pipedrive

The hermes Custom Field object:
```
machine_name - str: the name of the field in snake_case
name - str: the name of the field
field_type - str: the type of the field (str, int, bool, fk_field)
hermes_field_name - str: the name of the field in the hermes object
tc2_machine_name - str: the name of the field in the tc2 object
pd_field_id - str: the id of the field in pipedrive
linked_object_type - str: the type of object the field is linked to (Company, Contact, Deal, Meeting)
```


`hermes_field_name` and `tc2_machine_name` are used to determine where the data is coming from, 

if `hermes_field_name` is set, then the data is coming from hermes, these will be attribute names on hermes objects, i.e `paid_invoice_count`
if `tc2_machine_name` is set, then the data is coming from TC2 extra attrs

if we want to get and modify a field on a TC2 Object which is not in extra attrs, we need to manually code it into hermes, then use `hermes_field_name` to get the data from hermes.


`pd_field_id`: inside the objects returned from Pipedrive, the Data fields key is a uuid that is unique to the field, so we need to get the key from the Pipedrive API.
Data fields > Choose the object tab (Lead/deal, Person, Organization, Product), and select the field you want to get the key for, then select the ... and select `Copy API key` (this will copy the key to your clipboard


#### Template Custom Field setup:  

| ID | machine_name | name | field_type | hermes_field_name | tc2_machine_name         | pd_field_id | linked_object_type |
|---|-------------|------|------------|-------------------|--------------------------|-------------|--------------------|
| 1 | website | Website | str        | website           | website                  | xxxxxxxxxxx | Company            |
| 2 | paid_invoice_count | Paid Invoice Count | int        | paid_invoice_count |                          | xxxxxxxxxxx | Company            |
| 3 | tc2_status | TC2 Status | str        | tc2_status        |                          | xxxxxxxxxxx | Company            |
| 4 | tc2_cligency_url | TC2 Cligency URL | str        | tc2_cligency_url  |                          | xxxxxxxxxxx | Company            |
| 5 | utm_source | UTM Source | str        | utm_source        | utm_source               | xxxxxxxxxxx | Company            |
| 6 | utm_campaign | UTM Campaign | str        | utm_campaign      | utm_campaign             | xxxxxxxxxxx | Company            |
| 7 | estimated_monthly_income | Estimated Monthly Income | str        | estimated_income | estimated_monthly_income | xxxxxxxxxxx | Company            |
| 8 | currency | Currency | str        | currency          | currency                 | xxxxxxxxxxx | Company            |
| 8 | support_person_id | Support Person ID | fk_field   | support_person    |                          | xxxxxxxxxxx | Company            |
| 9 | bdr_person_id | BDR Person ID | fk_field   | bdr_person        |                          | xxxxxxxxxxx | Company            |
| 10 | signup_questionnaire | Signup Questionnaire | str        | signup_questionnaire | signup_questionnaire     | xxxxxxxxxxx | Company            |
| 11 | hermes_id | Hermes ID | fk_field   | id                |                          | xxxxxxxxxxx | Company            |
| 12 | hermes_id | Hermes ID | fk_field   | id                |                          | xxxxxxxxxxx | Contact            |
| 13 | hermes_id | Hermes ID | fk_field   | id                |                          | xxxxxxxxxxx | Deal               |


- replace `xxxxxxxxxxx` with the `pd_field_id` from pipedrive, you can get this by selecting the field in pipedrive and selecting the ... then `Copy API key`




### Ngrok:  
We use ngrok to expose our local hermes server to the internet, so that we can receive webhooks from Pipedrive.
 
run ngrok on port 8000  
  
`ngrok http --${your ngrok domain} 8000`  
  
set the `HERMES_URL` env var to the ngrok url provided.

HINT: if you create a account with ngrok, it will give you a static url that you can use for the webhooks, that will never expire ;)


### Back in Pipedrive lets setup the pipelines and stages:
- navigate to Deals tab, then in the top right it will have a button 'Pipeline' with a pencil icon, click on that
- now you can rename the default pipeline to `PAYG`
- Also edit the stage names, be sure to include the pipeline name in the stage name, i.e `PAYG - Contacted`

then to create a new pipeline click the 'PAYG' dropdown and select 'Add new pipeline'

### Return to Hermes for the next steps:


#### Stages Tab

you should now see all the stages from pipedrive, with their associated `pd_stage_id`

- hint: if the stage is not there, go back to pipedrive and edit the name to trigger a webhook to update hermes


#### Pipelines Tab
  
You should now have 3 pipelines:
- `PAYG`  
- `STARTUP`  
- `ENTERPRISE`

Now edit each pipeline and set the `dft_entry_pipeline_stage` to the stage that the deal should be set to when it is first created in pipedrive. (warning, dropdown is not filtered by pipeline)  
  

#### Config Tab  

- Edit existing config and set the pipline stages to their associated Hermes Stage IDs


#### Setup Callbooker:  
  
in order for the callbooker to work on tutorcruncher.com, you need to set the following env vars:  
- set `DEV_MODE=True` in `.env`  
- set `G_PRIVATE_KEY` in `.env` to the private key of the google service account  
- set `G_PRIVATE_KEY_ID` in `.env` to the private key id of the google service account  
  
Ensure admin has a matching email address to the one in the sales or support team (i.e fionn@tutorcruncher.com)  
  
##### Edit in tutorcruncher.com
- `sales_reps.yml` and `support_reps.yml`, `hermes_admin_id` to match the sales and support admins ids in hermes.
- set `HERMES_URL` = `http://localhost:8000`

## Extra Tips
### How to add a new custom field to Pipedrive:

For example we have a new field on the TC2 Cligency called `signup_questionnaire` that we want to add to the Organization in Pipedrive.

1. Create the field in Pipedrive: [here](https://tutorcruncher.pipedrive.com/settings/fields?type=ORGANIZATION)
   1. Be sure the name you set is lowercase and snake_case (with underscrolls) (i.e `signup_questionnaire`)
   2. Set the field type to `Large text` (or whatever type you need)
2. get the field key from the Pipedrive API by selecting the ... on the field and selecting `Copy API key`
3. Now in hermes, navigate to the Custom Fields tab:
   1. Create a new Custom Field
   2. set the machine_name to the same snake_case name as the field in pipedrive (i.e `signup_questionnaire`)
   3. set the Name to the name of the field in pipedrive (i.e `Signup Questionnaire`)
   4. set the field_type to the type of the field in pipedrive (i.e `str`)
   5. next set the value of either `hermes_field_name` or `tc2_machine_name` to that of the source data location i.e `signup_questionnaire` is coming from TC2 so set `tc2_machine_name` to `signup_questionnaire` and leave `hermes_field_name` blank.
   6. set the `pd_field_id` to the field key you got from the pipedrive API (i.e `d4db234b06f753a951c0de94456740f270e0f2ed`)
   7. set the `Linked Object Type` to the hermes object type that the field is linked to (i.e `Company`) 


### if in doubt, restart the server
- When updating and saving anything in the hermes admin, you should restart the server to ensure the changes are picked up. :exploading_head:


### Basic setup dumps

- I have created a couple basic setup dumps that you can use to get started with the basic setup of the system, you can find them [here](https://drive.google.com/drive/folders/1b-ldYBI5gyUQiC62zNLgglmux0_n4U-y?usp=drive_link)

## Testing  

Unittests can be run with `make test`. You will need to install the test dependencies with `make install-dev` first.


- be sure to login to meta with one of ur newly created admins and NOT `testing@tutorcruncher.com`, as superadmins dont trigger actions and webhooks to be sent :exploding_head:
- you can set the password of one of your newly created admins like this:
```
Administrator.objects.get(id=68).user
user = _
user.set_password('testing')
user.save(update_fields=['password'])
```
### Example testing workflows:

#### Company Signup:
- in TC2 signup form (`/start/1`), fill in the details and submit
- This will create the Cligency in TC2
- This will trigger a webhook to create a Company in Hermes
- Hermes will create the Organization in Pipedrive



### Testing with live data

to test with live data, run `make restore-from-live` to download and restore the live database to your local machine.

also add your `{your ngork url}/pipedrive/callback` to TutorCruncher Pipedrive webhooks,

then you should see all the webhooks and responses in both your local nrork site and any changes you make in pipedrive will be reflected in your local database.

## Migrations

We use `aerich` to create and run migrations.

If you have changed a model then you can create migrations with `aerich migrate`. A new file will be created in the `migrations/models` directory. If you need to run any migrations, use `aerich upgrade`.

If you mess up your migrations, you can reset the database with `make reset-db`. Delete the migrations folder and run `aerich init-db` to recreate the migrations folder and create the initial migration.

More details can be found in the aerich docs.

## Deploying to Heroku  
Create Meta Admins for the sales and support teams in TC2, and heremes, ensuring their tc2_admin_id matches the one in hermes. 


## Writing a Patch

- In the patch.py file, create a new function that will be your patch.
- The function needs to be made between the # Start of patch commands and # End of patch commands.
- The function needs to have the @command decorator.

#### Running a Patch
```
python patch.py <patch_name>
```

