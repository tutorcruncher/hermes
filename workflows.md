# Workflows

Here is a list of hopefully all actions inside the various systems and what they should do to keep everything in sync.

## Actions inside Pipedrive

We have two systems to update when something happens inside Pipedrive: Hermes and TC2. The further expected actions that should happen are denoted by the following:
[H-IN] - The Object(s) exists in Hermes
[H-EX] - The Object(s) doesn't exist in Hermes
[TC2-IN] - The Object(s) exists in TC2
[TC2-EX] - The Object(s) doesn't exist in TC2

### Org actions

* [ ] Create Org
  * [X] [H-IN] - Update the Company with any relevant data. **TODO: Currently we will create a new Company, as we only match on pipedrive_id. See TODO in `_process_pd_organisation`.**
  * [X] [H-EX] - Create the Company. `Company.sales_person` is populated by Owner. 
  * [ ] [TC2-IN] - Update the TC2 lCligency with any relevant data.
  * [X] [TC2-EX] - Nothing happens
* [ ] Update Org
  * [X] [H-IN] - Update the Company with any relevant data.
  * [X] [H-EX] - Create the Company. `Company.sales_person` is populated by Owner. 
  * [ ] [TC2-IN] - Update the TC2 Cligency with any relevant data. Ignore SRs.
  * [X] [TC2-EX] - Nothing happens
* [X] Delete Org
  * [X] [H-IN] - Delete
  * [X] [H-EX] - Nothing
  * [X] [TC2-IN] - Nothing
  * [X] [TC2-EX] - Nothing
* [X] Delete Org not in Hermes
  * [X] [H-IN] - Nothing
  * [X] [H-EX] - Nothing
  * [X] [TC2-IN] - Nothing
  * [X] [TC2-EX] - Nothing

### Person actions

* [X] Create Person with Org
  * [ ] [H-IN] - Update the Contact with relevant data. **TODO: Currently we will create a new Contact, as we only match on pipedrive_id. See TODO in `_process_pd_person`.**
  * [X] [H-EX]
    *  [X] If the Org exists, create the Contact and set the Org.
    *  [X] If the Org doesn't exist, create the Org and Contact. `Company.sales_person` is populated by Owner.
  * [X] [TC2-IN] - Do nothing
  * [X] [TC2-EX] - Do nothing
* [X] Create Person without Org
  * [X] [H-IN] - Nothing
  * [X] [H-EX] - Nothing
  * [X] [TC2-IN] - Nothing
  * [X] [TC2-EX] - Nothing
* [X] Update Person with Org
  * [X] [H-IN] - Update the Contact with relevant data.
  * [X] [H-EX] - Create the Contact and Company. `Company.sales_person` is populated by Owner.
  * [X] [TC2-IN] - Do nothing
  * [X] [TC2-EX] - Do nothing
* [X] Update Person without Org
  * [X] [H-IN] - Nothing
  * [X] [H-EX] - Nothing
  * [X] [TC2-IN] - Nothing
  * [X] [TC2-EX] - Nothing
* [X] Delete Person with Org with Owner
  * [X] [H-IN] - Remove the Contact from the Company.
  * [X] [H-EX] - Do nothing
  * [X] [TC2-IN] - Do nothing
  * [X] [TC2-EX] - Do nothing
* [X] Delete Person not in Hermes
  * [X] [H-IN] - Do nothing
  * [X] [H-EX] - Do nothing
  * [X] [TC2-IN] - Do nothing
  * [X] [TC2-EX] - Do nothing
* [ ] Merge Contacts?? **Need to deal with**

### Deal actions

Assume for these that the above logic applies to the Org and Person, which follows the rules
* If the Org doesn't exist, create it in Hermes.
* If the Person doesn't exist, only create them if the Org exists.
* We do nothing in TC **in relation to the Org and Person objects**.

* [X] Create Deal with Org that exists in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that exists in Hermes & Pipedrive, Person doesn't exist in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage TODO
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that doesn't exist in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage TODO
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that exists in Hermes but not Pipedrive, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that exists in Hermes but not Pipedrive, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that doesn't exist in either, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that exists in Pipedrive but not Hermes, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that exists in Pipedrive but not Hermes, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Create Deal with Org that doesn't exist in either, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Create Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Hermes & Pipedrive, Person doesn't exist in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that doesn't exist in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Hermes but not Pipedrive, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Hermes but not Pipedrive, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that doesn't exist in either, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Pipedrive but not Hermes, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that exists in Pipedrive but not Hermes, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Update Deal with Org that doesn't exist in either, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Update Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Hermes & Pipedrive, Person doesn't exist in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that doesn't exist in Hermes & Pipedrive, Person exists in Hermes & Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Hermes but not Pipedrive, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Hermes but not Pipedrive, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that doesn't exist in either, Person exists in Hermes but not Pipedrive
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Pipedrive but not Hermes, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that exists in Pipedrive but not Hermes, Person doesn't exist in either
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A
* [ ] Delete Deal with Org that doesn't exist in either, Person exists in Pipedrive but not Hermes
  * [X] [H-IN] - N/A
  * [X] [H-EX] - Delete Deal
  * [ ] [TC2-IN] - **Cligency exists** - Update Cligency with Deal stage
  * [X] [TC2-EX] - N/A

### Pipeline actions

* [X] Create Pipeline
* [X] Update Pipeline
* [X] Delete Pipeline **Doesn't seem possible**

### Stage actions

* [X] Create Stage
* [X] Update Stage
* [X] Delete Stage

## Actions inside TC2

We have two systems to update when something happens inside TC2: Hermes and Pipedrive. The further expected actions that should happen are denoted by the following:
[H-IN] - The Object(s) exists in Hermes
[H-EX] - The Object(s) doesn't exist in Hermes
[PD-IN] - The Object(s) exists in Pipedrive
[PD-EX] - The Object(s) doesn't exist in Pipedrive

## Cligency actions

* [ ] Cligency created, they exist already in Pipedrive
  * [ ] [H-IN] - Update the Company with the TC2 ID (matching on company name and contact email) **TODO: Currently we will create a new Company/Contact, as we only match on ID. See TODO in `_create_or_update_company`.**
  * [ ] [H-EX] - In theory this shouldn't be possible. Currently we'll create a new Company/Contact
  * [ ] [PD-IN] - Update the Org with the TC2 status and ID
  * [ ] [PD-EX] - Create the Org and Person
* [ ] Cligency updated
  * [ ] [H-IN] - Update the Company with the TC2 ID (matching on company name and contact email) **TODO: Currently we will create a new Company/Contact, as we only match on ID. See TODO in `_create_or_update_company`.**
  * [ ] [H-EX] - In theory this shouldn't be possible. Currently we'll create a new Company/Contact
  * [ ] [PD-IN] - Update the Org with the TC2 status and ID
  * [ ] [PD-EX] - Create the Org and Person
* [ ] Cligency deleted
  * [ ] [H-IN] - Delete the Company and Contact
  * [ ] [H-EX] - Do nothing
  * [ ] [PD-IN] - Do nothing
  * [ ] [PD-EX] - Do nothing

## Actions from the Callbooker

We have three systems to update when a call is booked using the Callbooker: TC2, Hermes and Pipedrive. There are quite a lot of different actions to test:


* [ ] Sales call booked
  * [ ] In Hermes:
    * [ ] Company object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name). Assign owner from admin.
      * [ ] If it exists, do nothing
    * [ ] Contact object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * [ ] Deal object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists, do nothing
    * [ ] Meeting object:
       * [ ] If one exists for the Contact within 2 hours, don't create it
       * [ ] If one cannot be created because the admin is bsuy, don't create it
       * [ ] Else create it
  *  [ ] In Pipedrive
    * [ ] Org object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * [ ] Person object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * [ ] Deal object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists, do nothing
    * [ ] Activity object:
      * [ ] If the Meeting was created in Hermes, create it
* [ ] Support call booked
  * [ ] In Hermes:
    * [ ] Company object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * [ ] Contact object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * [ ] Deal object:
      * [ ] Do nothing
    * [ ] Meeting object:
       * [ ] If one exists for the Contact within 2 hours, don't create it
       * [ ] If one cannot be created because the admin is bsuy, don't create it
       * [ ] Else create it
  *  [ ] In Pipedrive
    * [ ] Org object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * [ ] Person object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * [ ] Deal object:
      * [ ] Do nothing
    * [ ] Activity object:
      * [ ] If the Meeting was created in Hermes, create it


# TODO: 

* [ ] If a company is changed in TC to have it's PD org ID set, then it should be linked to the company in PD
* [ ] Deal with merging Orgs/Persons.
