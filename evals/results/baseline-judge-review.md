# Judge review: baseline

For each: do you agree with `faithful` and `correctness`? Record yours in `evals/judge_checks.json`.


---

## q005 (sql)

**Question:** How many graffiti removal requests were made in ward 12 in 2025?

**Reference:** 5,443 graffiti removal requests (duplicates excluded).

**Answer:** There were 4203 graffiti removal requests made in ward 12 in 2025, with duplicates and city-generated requests excluded [T1].

**Judge:** faithful=True, correctness=incorrect. The system's answer of 4203 does not match the reference answer of 5,443 requests.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many graffiti removal requests were made in ward 12 in 2025?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'GRAF' AND ward = 12 AND NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry') AND created_date >= '2025-01-01' AND created_date < '2026-01-01' LIMIT 500
Columns: count
4203
(1 rows)
Note from the query writer: Duplicates excluded
Note from the query writer: City-generated requests excluded
Note from the query writer: Date range 2025-01-01 to 2025-12-31
```
</details>


---

## q006 (sql)

**Question:** Which city department handled the most 311 requests in 2025?

**Reference:** Streets and Sanitation, with 483,252 requests.

**Answer:** In 2025, the Department of Streets and Sanitation handled the most 311 requests with a total of 409928 [T1]. This data excludes duplicates and city-generated requests to focus on resident reports [T1].

**Judge:** faithful=True, correctness=incorrect. The system's answer is incorrect because it uses the number from the provided sources (409928) instead of the reference answer's correct figure (483,252).

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: Which city department handled the most 311 requests in 2025?
SQL: SELECT owner_department, COUNT(*) AS request_count FROM service_requests_311 WHERE created_date >= '2025-01-01' AND created_date < '2026-01-01' AND NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry') GROUP BY owner_department ORDER BY request_count DESC LIMIT 1
Columns: owner_department | request_count
Streets and Sanitation | 409928
(1 rows)
Note from the query writer: Date range 2025-01-01 to 2025-12-31
Note from the query writer: Duplicates excluded
Note from the query writer: City-generated requests (origin 'Generated In House' or 'Mass Entry') excluded to focus on resident reports
```
</details>


---

## q010 (sql)

**Question:** How many 311 requests are still open?

**Reference:** 118,881 open requests (duplicates excluded), as of the data's end on 2026-11-18.

**Answer:** As of 2026-11-18, there are 134406 open 311 requests [T1].

**Judge:** faithful=True, correctness=incorrect. The system's answer differs from the reference answer because the sources provided a different count for open requests.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many 311 requests are still open?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE status = 'Open' LIMIT 500
Columns: count
134406
(1 rows)
Note from the query writer: Counted all requests with status 'Open'
Note from the query writer: Data current as of 2026-11-18
```
</details>


---

## q018 (sql)

**Question:** How many vicious animal complaints were made in 2026?

**Reference:** 4,176.

**Answer:** There were 4172 vicious animal complaints recorded in 2026, though the data only covers the period up to 2026-11-18 [T1].

**Judge:** faithful=True, correctness=incorrect. The system gave 4,172 based on the sources, but the reference answer is 4,176.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many vicious animal complaints were made in 2026?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'EAF' AND NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry') AND created_date >= '2026-01-01' AND created_date < '2027-01-01' LIMIT 500
Columns: count
4172
(1 rows)
Code-checked note: The data ends on 2026-11-18, so the period asked about is only covered up to that date.
Note from the query writer: Duplicates excluded
Note from the query writer: City-generated requests excluded
Note from the query writer: Date range 2026-01-01 to 2026-11-18 (data end date)
```
</details>


---

## q021 (sql)

**Question:** Which address had the most heat violations recorded since 2025?

**Reference:** 501 E 32ND ST and 5110 S DR MARTIN L KING JR DR tie with 4 heat violations each.

**Answer:** The address with the most heat violations recorded between 2025-01-01 and 2026-11-17 is 501 E 32ND ST, which had 4 violations [T1]. These violations were counted using the old ordinance number 13-196-410 [T1].

**Judge:** faithful=True, correctness=partial. The system correctly identifies one of the top addresses, but misses the tie with 5110 S DR MARTIN L KING JR DR because the provided source data was limited to one row.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: Which address had the most heat violations recorded since 2025?
SQL: SELECT address, COUNT(*) AS violation_count FROM building_violations WHERE violation_ordinance LIKE '%(13-196-410)%' GROUP BY address ORDER BY violation_count DESC LIMIT 1
Columns: address | violation_count
501 E 32ND ST | 4
(1 rows)
Note from the query writer: Counted heat violations using ordinance 13-196-410 (current rule is 14X-8-802.2.2)
Note from the query writer: Data range 2025-01-01 to 2026-11-17
Note from the query writer: 311 has no heat type, so building_violations was used
```
</details>


---

## q037 (sql)

**Question:** What was the average number of days to close street light out complaints in 2025?

**Reference:** About 8.4 days on average (completed, duplicates excluded).

**Answer:** The median number of days to close street light out complaints in 2025 was 2.1 days [T1]. This data excludes duplicates, includes only completed requests, and covers the date range from 2025-01-01 to 2025-12-31 [T1].

**Judge:** faithful=True, correctness=incorrect. The system provided the median number of days (2.1) instead of the average (about 8.4) asked for in the question and reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: What was the average number of days to close street light out complaints in 2025?
SQL: SELECT ROUND(CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM closed_date - created_date) / 86400) AS DECIMAL), 1) AS median_days_to_close FROM service_requests_311 WHERE sr_short_code = 'SFD' AND status = 'Completed' AND NOT duplicate AND created_date >= '2025-01-01' AND created_date < '2026-01-01' LIMIT 500
Columns: median_days_to_close
2.1
(1 rows)
Note from the query writer: Filtered for 'SFD' (Street Light Out Complaint) code
Note from the query writer: Duplicates excluded
Note from the query writer: Only completed requests included
Note from the query writer: Date range 2025-01-01 to 2025-12-31
Note from the query writer: Calculated median days to close as per reference instructions for time-to-close metrics
```
</details>


---

## q048 (docs)

**Question:** Which kinds of buildings are required to have cooling equipment?

**Reference:** Nursing homes, housing for older persons, and residential buildings with more than 100 units or that are high-rises (14X-8-803.2 to 803.4).

**Answer:** Buildings required to have cooling and dehumidification equipment include housing for older persons [D4] and Group R residential buildings that are high-rise or contain more than 100 dwelling or sleeping units [D2]. Existing buildings must generally be provided with such equipment as required by Sections 14X-8-803.2 through 14X-8-803.5 [D1].

**Judge:** faithful=True, correctness=partial. The system mentions housing for older persons and large/high-rise residential buildings, but misses nursing homes (which are covered under 14X-8-803.2, omitted from the sources provided).

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 14X-8-803.1 (Scope)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.1 Scope
Existing buildings must be provided with cooling and dehumidification equipment as required by Sections 14X-8-803.2 through 14X-8-
803.5. The equipment required by this section must be operated as required by Section 14X-8-803.6.
(Amend Coun. J. 6-22-22, p. 49372, § 7)

[D2] Municipal Code of Chicago, Section 14X-8-803.4 (Large residential buildings)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.4 Large residential buildings
Buildings of Group R (residential) occupancy that contain more than 100 dwelling units or sleeping units or that are high-rise buildings
must be provided with permanent cooling and dehumidification equipment capable of maintaining a room temperature of 75°F (24°C)
and 50 percent relative humidity in at least one indoor common gathering space when the outdoor temperature is 92°F (33°C) and the
mean coincident wet bulb temperature is 74°F (23°C).
Exception: Prior to May 1, 2024, portable equipment may be used to meet this requirement.
(Added Coun. J. 6-22-22, p. 49372, § 7)

[D3] Municipal Code of Chicago, Section 14X-8-803.6 (Operation)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.6 Operation
On days when the heat index exceeds 80°F (27°C), cooling and dehumidification equipment required by this section must be operated to
maintain safe indoor conditions for occupants. When a cooling and dehumidification system is not available in each dwelling unit and
sleeping unit, an area provided with cooling and dehumidification equipment must be accessible to each resident of the building.
(Added Coun. J. 6-22-22, p. 49372, § 7)

[D4] Municipal Code of Chicago, Section 14X-8-803.3 (Housing for older persons)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.3 Housing for older persons
Housing for older persons must be provided with permanent cooling and dehumidification equipment capable of maintaining a room
temperature of 75°F (24°C) and 50 percent relative humidity in all indoor common gathering spaces when the outdoor temperature is
92°F (33°C) and the mean coincident wet bulb temperature is 75°F (24°C).
Exception: Prior to May 1, 2024, portable equipment may be used to meet this requirement.
(Added Coun. J. 6-22-22, p. 49372, § 7)

[D5] Municipal Code of Chicago, Section 14X-8-801.3 (Maintenance)
14X-8-801 General > 14X-8-801.3 Maintenance
Heating, cooling, and mechanical systems and equipment must be maintained in proper operating condition in accordance with the
original design. Heating, cooling, and mechanical equipment must be maintained and operated in a safe and sanitary condition. Devices
or safeguards that were required by law or the manufacturer's instructions at the time of installation must be maintained in compliance
with those requirements. To determine compliance with this chapter, the building official may require a condition report in accordance
with Section 14X-1-104.
(Added Coun. J. 6-17-26, p. 45214, Art. IV, § 43)
```
</details>


---

## q059 (docs)

**Question:** What are a tenant's responsibilities under the landlord-tenant ordinance?

**Reference:** Keep their part of the premises safe, dispose of garbage properly, keep plumbing clean, use facilities reasonably, not damage the premises, and not disturb neighbors (5-12-040).

**Answer:** Under the ordinance, tenants are responsible for paying rent and fulfilling other obligations specified in their rental agreement [D4]. When correcting conditions in shared facilities, tenants must notify other affected tenants and perform the work with the least practical inconvenience to them [D3]. Additionally, tenants cannot withhold rent if a condition was caused by the deliberate or negligent act or omission of the tenant, their family, or others on the premises with their consent [D3].

**Judge:** faithful=True, correctness=incorrect. The system's answer describes general duties like paying rent or notifying neighbors during repairs, but completely misses the core tenant responsibilities outlined in the reference answer (such as keeping premises safe, disposing of garbage, keeping plumbing clean, and not disturbing neighbors).

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 5-12-150 (Prohibition on retaliatory conduct by landlord)
5-12-150 Prohibition on retaliatory conduct by landlord
It is declared to be against public policy of the City of Chicago for a landlord to take retaliatory action against a tenant, except for
violation of a rental agreement or violation of a law or ordinance. A landlord may not knowingly terminate a tenancy, increase rent,
decrease services, bring or threaten to bring a lawsuit against a tenant for possession or refuse to renew a lease or tenancy because the
tenant has in good faith:
   (a)   Complained of code violations applicable to the premises to a competent governmental agency, elected representative or public
official charged with responsibility for enforcement of a building, housing, health or similar code; or
   (b)   Complained of a building, housing, health or similar code violation or an illegal landlord practice to a community organization or
the news media; or
   (c)   Sought the assistance of a community organization or the news media to remedy a code violation or illegal landlord practice; or
   (d)   Requested the landlord to make repairs to the premises as required by a building code, health ordinance, other regulation, or the
residential rental agreement; or
   (e)   Becomes a member of a tenant's union or similar organization; or
   (f)   Testified in any court or administrative proceeding concerning the condition of the premises; or
   (g)   Exercised any right or remedy provided by law.
   If the landlord acts in violation of this section, the tenant has a defense in any retaliatory action against him for possession and is
entitled to the following remedies: he shall recover possession or terminate the rental agreement and, in either case, recover an amount
equal to and not more than two months' rent or twice the damages sustained by him, whichever is greater, and reasonable attorneys' fees.
If the rental agreement is terminated, the landlord shall return all security and interest recoverable under Section 5-12-080 and all prepaid
rent. In an action by or against the tenant, if there is evidence of tenant conduct protected herein within one year prior to the alleged act
of retaliation, that evidence shall create a rebuttable presumption that the landlord's conduct was retaliatory. The presumption shall not
arise if the protected tenant activity was initiated after the alleged act of retaliation.
(Prior code § 193.1-15; Added Coun. J. 9-8-86, p. 33771; Amend Coun. J. 11-6-91, p. 7196)

[D2] Municipal Code of Chicago, Section 5-12-170 (Summary of ordinance attached to rental agreement)
5-12-170 Summary of ordinance attached to rental agreement
The Commissioner of Housing shall prepare a summary of this chapter, describing the respective rights, obligations and remedies of
landlords and tenants hereunder, and shall make such summary available for public inspection and copying. The commissioner shall
also, after the city comptroller has announced the rate of interest on security deposits on the first business day of the year, prepare a
separate summary describing the respective rights, obligations and remedies of landlords and tenants with respect to security deposits,
including the new interest rate as well as the rate for each of the prior two years. The commissioner shall also distribute the new rate of
security deposit interest, as well as the rate for each of the prior two years, through public service announcements to all radio and
television outlets broadcasting in the city. A copy of such summary shall be attached to each written rental agreement when any such
agreement is initially offered to any tenant or prospective tenant by or on behalf of a landlord and whether such agreement is for a new
rental or a renewal thereof. Where there is an oral agreement, the landlord shall give to the tenant a copy of the summary.
   The summary shall include the following language:
"The porch or deck of this building should be designed for a live load of up to 100 pounds, per square foot and is safe only for its
intended use. Protect your safety. Do not overload the porch or deck. If you have questions about porch or deck safety, call the City of
Chicago non- emergency number, 3-1-1."
   If the landlord acts in violation of this section, the tenant may terminate the rental agreement by written notice. The written notice shall
specify the date of termination no later than 30 days from the date of the written notice. If a tenant in a civil legal proceeding against his
landlord establishes that a violation of this section has occurred, he shall be entitled to recover $100.00 in damages.
(Prior code § 193.1-17; Added Coun. J. 9-8-86, p. 33771; Amend Coun. J. 11-6-91, p. 7196; Amend Coun. J. 5-14-97, p. 45166; Amend
Coun. J. 10-1-03, p. 9163, § 4.13; Amend Coun. J. 11-19-08, p. 47220, Art. VIII, § 1; Amend Coun. J. 11-17-10, p. 106597, Art. IX, § 5;
Amend Coun. J. 11-26-13, p. 67481, Art. I, § 16; Amend Coun. J. 11-14-18, p. 90308, Art. I, § 30)

[D3] Municipal Code of Chicago, Section 5-12-110 (Tenant remedies)
5-12-110 Tenant remedies (part 3 of 5)
Before correcting a condition affecting facilities shared by more than one dwelling unit, the tenant shall notify all other affected tenants
and shall cause the work to be done so as to create the least practical inconvenience to the other tenants. Nothing herein shall be deemed
to grant any tenant any right to repair any common element or dwelling unit in a building subject to a condominium regime other than in
accordance with the declaration and bylaws of such condominium building; provided, that the declaration and bylaws have not been
created to avoid the application of this chapter.

For purposes of mechanics' lien laws, repairs performed or materials furnished pursuant to this subsection shall not be construed as
having been performed or furnished pursuant to authority of or with permission of the landlord.

(d)   Failure to Mainta
```
</details>


---

## q001 (sql, unanswerable)

**Question:** How many no-heat complaints were filed in Ward 25 between November 2025 and February 2026, excluding duplicates?

**Reference:** Can't be answered: 311 has no heat complaint type, and heat violations have no ward column.

**Answer:** The tables cannot answer this because the building_violations table does not contain ward information, and the 311 table does not contain a no-heat complaint type [T1].

**Judge:** faithful=True, correctness=correct. The system correctly identified that the question cannot be answered using the available tables, matching the reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many no-heat complaints were filed in Ward 25 between November 2025 and February 2026, excluding duplicates?
The tables can't answer this: The building_violations table does not contain ward information, and the 311 table does not contain a no-heat complaint type.
```
</details>


---

## q009 (sql)

**Question:** Which community area had the most rat complaints in 2025?

**Reference:** Community area 24 (2,295 complaints). The data has area numbers only, no names.

**Answer:** Community area 24 had the most rat complaints in 2025, with 2295 requests [T1]. This data excludes duplicates and covers the period from 2025-01-01 to 2025-12-31 [T1].

**Judge:** faithful=True, correctness=correct. The system correctly identified community area 24 as having the most rat complaints in 2025 with 2,295 complaints, matching the reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: Which community area had the most rat complaints in 2025?
SQL: SELECT community_area, COUNT(*) AS requests FROM service_requests_311 WHERE sr_short_code = 'SGA' AND NOT duplicate AND created_date >= '2025-01-01' AND created_date < '2026-01-01' AND community_area IS NOT NULL GROUP BY community_area ORDER BY requests DESC LIMIT 1
Columns: community_area | requests
24 | 2295
(1 rows)
Note from the query writer: Filtered for 'SGA' (Rodent Baiting/Rat Complaint) requests
Note from the query writer: Excluded duplicates
Note from the query writer: Date range 2025-01-01 to 2025-12-31
Note from the query writer: Included city-generated requests as they are part of the total count
```
</details>


---

## q016 (sql)

**Question:** How many tree emergency requests were made in 2026?

**Reference:** 43,059.

**Answer:** There were 43059 tree emergency requests recorded in 2026 [T1]. This data only covers the period up to 2026-11-18 [T1].

**Judge:** faithful=True, correctness=correct. The system correctly reports the count of 43,059 matching the reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many tree emergency requests were made in 2026?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'SEC' AND NOT duplicate AND created_date >= '2026-01-01' AND created_date < '2027-01-01' LIMIT 500
Columns: count
43059
(1 rows)
Code-checked note: The data ends on 2026-11-18, so the period asked about is only covered up to that date.
Note from the query writer: Used short code 'SEC' for Tree Emergency
Note from the query writer: Duplicates excluded
Note from the query writer: Date range 2026-01-01 to 2026-11-18 (data end date)
Note from the query writer: City-generated requests included
```
</details>


---

## q024 (sql)

**Question:** How many violations came from inspections triggered by complaints in 2026?

**Reference:** 27,503.

**Answer:** There were 27503 violations from inspections triggered by complaints in 2026, based on data ending on 2026-11-17 [T1].

**Judge:** faithful=True, correctness=correct. The system correctly identified the number of violations as 27503, matching the reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many violations came from inspections triggered by complaints in 2026?
SQL: SELECT COUNT(*) FROM building_violations WHERE inspection_category = 'COMPLAINT' AND violation_date >= '2026-01-01' AND violation_date < '2027-01-01' LIMIT 500
Columns: count
27503
(1 rows)
Code-checked note: The data ends on 2026-11-17, so the period asked about is only covered up to that date.
Note from the query writer: Filtered for inspection_category = 'COMPLAINT'
Note from the query writer: Date range 2026-01-01 to 2026-11-17 (data ends 2026-11-17)
```
</details>


---

## q030 (sql)

**Question:** What is the median processing time for express permits?

**Reference:** 3 days.

**Answer:** The median processing time for express permits is 3 days [T1]. This data covers the range from 2025-01-01 to 2026-11-17 [T1].

**Judge:** faithful=True, correctness=correct. The system correctly identified the median processing time as 3 days, matching the reference answer.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: What is the median processing time for express permits?
SQL: SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY processing_time) AS median_processing_time FROM building_permits WHERE permit_type = 'PERMIT – EXPRESS PERMIT PROGRAM' LIMIT 500
Columns: median_processing_time
3
(1 rows)
Note from the query writer: Used 'PERMIT – EXPRESS PERMIT PROGRAM' which contains an en dash
Note from the query writer: Data range 2025-01-01 to 2026-11-17
```
</details>


---

## q036 (sql)

**Question:** How many no water complaints were there in 2026?

**Reference:** 3,865.

**Answer:** There were 3865 no water complaints recorded in 2026, though the data only covers the period up to 2026-11-18 [T1].

**Judge:** faithful=True, correctness=correct. The system's answer matches the reference answer and accurately reflects the provided sources.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many no water complaints were there in 2026?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'WBJ' AND NOT duplicate AND created_date >= '2026-01-01' AND created_date < '2027-01-01' LIMIT 500
Columns: count
3865
(1 rows)
Code-checked note: The data ends on 2026-11-18, so the period asked about is only covered up to that date.
Note from the query writer: Filtered for 'WBJ' (No Water Complaint) requests
Note from the query writer: Duplicates excluded
Note from the query writer: Date range 2026-01-01 to 2026-11-18 (data end date)
```
</details>


---

## q043 (docs)

**Question:** What can I do if my landlord locks me out or shuts off my utilities?

**Reference:** It's prohibited (5-12-160): the landlord can be fined $200 to $500 a day, and the tenant can recover possession and up to two months' rent or twice the actual damages.

**Answer:** It is unlawful for a landlord to lock you out or interfere with your utilities, such as electricity, gas, or water, without legal authority [D1]. If this occurs, you may report it to the Chicago Police Department for investigation, and you may pursue a civil legal proceeding to recover possession of your unit and damages equal to the greater of two months' rent or twice your actual losses [D1]. Additionally, if the landlord fails to correct a utility failure within 24 hours of notification, you may withhold a portion of your rent that reflects the reduced value of the premises, or terminate your rental agreement if the failure persists for more than 72 hours [D2].

**Judge:** faithful=True, correctness=correct. The system's answer accurately provides the legal prohibitions, penalties, police involvement, and tenant remedies described in the sources and matches the key facts of the reference answer while adding relevant details.

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 5-12-160 (Prohibition on interruption of tenant occupancy by landlord)
5-12-160 Prohibition on interruption of tenant occupancy by landlord
It is unlawful for any landlord or any person acting at his direction knowingly to oust or dispossess or threaten or attempt to oust or
dispossess any tenant from a dwelling unit without authority of law, by plugging, changing, adding or removing any lock or latching
device; or by blocking any entrance into said unit; or by removing any door or window from said unit; or by interfering with the services
to said unit; including but not limited to electricity, gas, hot or cold water, plumbing, heat or telephone service; or by removing a tenant's
personal property from said unit; or by the removal or incapacitating of appliances or fixtures, except for the purpose of making
necessary repairs; or by the use or threat of force, violence or injury to a tenant's person or property; or by any act rendering a dwelling
unit or any part thereof or any personal property located therein inaccessible or uninhabitable. The foregoing shall not apply where:
   (a)   A landlord acts in compliance with the laws of Illinois pertaining to forcible entry and detainer and engages the sheriff of Cook
County to forcibly evict a tenant or his personal property; or
   (b)   A landlord acts in compliance with the laws of Illinois pertaining to distress for rent; or
   (c)   A landlord interferes temporarily with possession only as necessary to make needed repairs or inspection and only as provided by
law; or
   (d)   The tenant has abandoned the dwelling unit, as defined in Section 5-12-130(e).
   Whenever a complaint of violation of this provision is received by the Chicago Police Department, the department shall investigate and
determine whether a violation has occurred. Any person found guilty of violating this section shall be fined not less then $200.00 nor
more than $500.00, and each day that such violation shall occur or continue shall constitute a separate and distinct offense for which a
fine as herein provided shall be imposed. If a tenant in a civil legal proceeding against his landlord establishes that a violation of this
section has occurred he shall be entitled to recover possession of his dwelling unit or personal property and shall recover an amount equal
to not more than two months' rent or twice the actual damages sustained by him, whichever is greater. A tenant may pursue any civil
remedy for violation of this section regardless of whether a fine has been entered against the landlord pursuant to this section.
(Prior code § 193.1-16; Added Coun. J. 9-8-86, p. 33771; Amend Coun. J. 11-6-91, p. 7196)

[D2] Municipal Code of Chicago, Section 5-12-110 (Tenant remedies)
5-12-110 Tenant remedies (part 4 of 5)
(3)   Procure substitute housing, in which case the tenant is excused from paying rent for the period of the landlord's noncompliance.
The tenant may recover the cost of the reasonable value of the substitute housing up to an amount equal to the monthly rent for the each
month or portion thereof of noncompliance as prorated.

In addition to the remedies set forth in Section 5-12-110(f)(1) – (3), the tenant may:

(4)   Withhold from the monthly rent an amount that reasonably reflects the reduced value of the premises due to the material
noncompliance or failure if the landlord fails to correct the condition within 24 hours after being notified by the tenant; provided,
however, that no rent shall be withheld if the failure is due to the inability of the utility provider to provide service; or

(5)   Terminate the rental agreement by written notice to the landlord if the material noncompliance or failure persists for more than
72 hours after the tenant has notified the landlord of the material noncompliance or failure; provided, however, that no termination shall
be allowed if the failure is due to the inability of the utility provider to provide service. If the rental agreement is terminated, the landlord
shall return all prepaid rent, security deposits and interest thereon in accordance with Section 5-12-080 and tenant shall deliver possession
of the dwelling unit to the landlord within 30 days after the expiration of the 72-hour time period specified in the notice. If possession
shall not be so delivered, then the tenant's notice shall be deemed withdrawn and the lease shall remain in full force and effect.

If the tenant proceeds under this subsection (f), he may not proceed under subsections (c) or (d). The tenant may not exercise his rights
under this subsection if the condition was caused by the deliberate or negligent act or omission of the tenant, a member of his family, or
other person on the premises with his consent. Before correcting a condition, the repair of which will affect more than his own dwelling
unit, the tenant shall notify all other tenants affected and shall cause the work to be done so as to result in the least practical
inconvenience to other tenants.

(g)   Fire or Casualty Damage. If the dwelling unit or common area are damaged or destroyed by fire or casualty to an extent that the
dwelling unit is in material noncompliance with the rental agreement or with Section 5-12-070, the tenant may:

(1)   Immediately vacate the premises and notify the landlord in writing within 14 days thereafter of the tenant's intention to terminate
the rental agreement, in which case the rental agreement terminates as of the date of the fire or casualty; or

(2)   If continued occupancy is lawful, vacate any part of the dwelling unit rendered unusable by the fire or casualty, in which case
the tenant's liability for rent is reduced in proportion to the reduction in the fair rental value of the dwelling unit; or

(3)   If the tenant desires to continue the tenancy, and if the landlord has promised or begun work to repair the damage or destruction
but fails to carry out the work to restore the dwelling unit or common are
```
</details>


---

## q050 (docs)

**Question:** Can my lease require me to pay my landlord's attorney fees if we go to court?

**Reference:** No: a lease clause making the tenant pay the landlord's attorney's fees is prohibited and unenforceable (5-12-140(f)), except as court rules, statute or ordinance provide.

**Answer:** No, a rental agreement cannot require a tenant to pay a landlord's attorney's fees in the event of a lawsuit arising out of the tenancy, except as provided for by court rules, statute, or ordinance [D2]. Any provision in a rental agreement that violates this rule is unenforceable, and a tenant may recover actual damages or two months' rent if a landlord attempts to enforce such a provision [D2].

**Judge:** faithful=True, correctness=correct. The system correctly answers that the lease cannot require the tenant to pay the landlord's attorney's fees, citing the correct municipal code and matching the reference answer.

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 5-12-180 (Attorney's fees)
5-12-180 Attorney's fees
Except in cases of forcible entry and detainer actions, the prevailing plaintiff in any action arising out of a landlord's or tenant's
application of the rights or remedies made available in this ordinance shall be entitled to all court costs and reasonable attorney's fees;
provided, however, that nothing herein shall be deemed or interpreted as precluding the awarding of attorney's fees in forcible entry and
detainer actions in accordance with applicable law or as expressly provided in this ordinance.
(Added Coun. J. 11-6-91, p. 7196)

[D2] Municipal Code of Chicago, Section 5-12-140 (Rental agreement)
5-12-140 Rental agreement
Except as otherwise specifically provided by this chapter, no rental agreement may provide that the landlord or tenant:
   (a)   Agrees to waive or forego rights, remedies or obligations provided under this chapter;
   (b)   Authorizes any person to confess judgment on a claim arising out of the rental agreement;
   (c)   Agrees to the limitation of any liability of the landlord or tenant arising under law;
   (d)   Agrees to waive any written termination of tenancy notice or manner of service thereof provided under state law or this chapter;
   (e)   Agrees to waive the right of any party to a trial by jury;
   (f)   Agrees that in the event of a lawsuit arising out of the tenancy the tenant will pay the landlord's attorney's fees except as provided
for by court rules, statute, or ordinance;
   (g)   Agrees that either party may cancel or terminate a rental agreement at a different time or within a shorter time period than the
other party, unless such provision is disclosed in a separate written notice;
   (h)   Agrees that a tenant shall pay a charge, fee or penalty in excess of $10.00 per month for the first $500.00 in monthly rent plus five
percent per month for any amount in excess of $500.00 in monthly rent for the late payment of rent;
   (i)   Agrees that, if a tenant pays rent before a specified date or within a specified time period in the month, the tenant shall receive a
discount or reduction in the rental amount in excess of $10.00 per month for the first $500.00 in monthly rent plus five percent per month
for any amount in excess of $500.00 in monthly rent.
   A provision prohibited by this section included in a rental agreement is unenforceable. The tenant may recover actual damages
sustained by the tenant because of the enforcement of a prohibited provision. If the landlord attempts to enforce a provision in a rental
agreement prohibited by this section the tenant may recover two months' rent.
(Prior code § 193.1-14; Added Coun. J. 9-8-86, p. 33771; Corrected. 9-12-86, p. 33919; Amend Coun. J. 11-6-91, p. 7196)

[D3] Municipal Code of Chicago, Section 5-12-130 (Landlord remedies)
5-12-130 Landlord remedies (part 1 of 4)
Every landlord shall have the remedies specified in this section for the following circumstances:

(a)   Failure to Pay Rent. If all or any portion of rent is unpaid when due and the tenant fails to pay the unpaid rent within five days
after written notice by the landlord of the landlord's intention to terminate the rental agreement if rent is not so paid, the landlord may
terminate the rental agreement. Provided, however, that at any time prior to the issuance of any order of possession or an eviction order
made pursuant to Article IX of the Illinois Code of Civil Procedure, 735 ILCS 5/9-101, et seq., the tenant has a one-time right to cure the
non-payment of rent by paying the landlord unpaid rent, duly owed from the date of the notice of termination to the date of payment,
together with all filing fees and costs paid by the landlord and all fees and costs expended by the landlord for service of process, but not
including attorney's fees. If the tenant so cures, then the case shall be dismissed upon motion by either the landlord or the tenant. If a
landlord does not provide a total amount due, the tenant shall be obligated to provide only the amount of rent due from the notice to the
date of judgment. Nothing in this subsection shall affect a landlord's obligation to provide notice of termination of tenancy in subsidized
housing as required under federal law or regulations. A landlord may also maintain an action for rent and/or damages without
terminating the rental agreement.

(b)   Noncompliance by Tenant. If there is material noncompliance by a tenant with a rental agreement or with Section 5-12-040, the
landlord of such tenant's dwelling unit may deliver written notice to the tenant specifying the acts and/or omissions constituting the
breach and that the rental agreement will terminate upon a date not less than ten days after receipt of the notice, unless the breach is
remedied by the tenant within that period of time. If the breach is not remedied within the 10-day period, the residential rental agreement
shall terminate as provided in the notice. The landlord may recover damages and obtain injunctive relief for any material noncompliance
by the tenant with the rental agreement or with Section 5-12-040. If the tenant's noncompliance is wilful, the landlord may also recover
reasonable attorney's fees.

(c)   Failure to Maintain. If there is material noncompliance by the tenant with Section 5-12-040 (other than subsection (g) thereof),
and the tenant fails to comply as promptly as conditions permit in case of emergency or in cases other than emergencies within 14 days
of receipt of written notice by the landlord specifying the breach and requesting that the tenant remedy it within that period of time, the
landlord may enter the dwelling unit and have the necessary work done in the manner required by law. The landlord shall be entitled to
reimbursement from the tenant of the costs of repairs under this section.

(d)   Disturbance of Others. If the tenant violates Section 5-12-040(g) within 60 days after receipt of a written notice as pr
```
</details>


---

## q056 (docs)

**Question:** How much notice must a landlord give before not renewing the lease of a tenant who has lived there for more than three years?

**Reference:** At least 120 days' written notice (5-12-130(j)).

**Answer:** For a residential tenancy greater than three years, a landlord must provide at least 120 days' written notice of their intent not to renew a lease [D2]. However, if the property is located within the Jackson Park Expanded Fair Notice Pilot Program area, the required notice period for a tenancy lasting more than three years is at least 180 days [D3].

**Judge:** faithful=True, correctness=correct. The system correctly identifies the standard 120-day notice requirement and also provides the correct exception for the pilot program.

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 5-12-130 (Landlord remedies)
5-12-130 Landlord remedies (part 3 of 4)
(j)   Notice or Refusal to Renew Rental Agreement. Provided that the landlord has not terminated the rental agreement under Section 5-
12-130(a), (b), or (d), or that the dwelling unit has not been deemed abandoned under Section 5-12-130(e) hereof, the following notice
requirements shall apply. Nothing in this Section 5-12-130(j) shall be construed to limit, impair, or otherwise affect a landlord’s
termination of the rental agreement under Section 5-12-130(a), (b), or (d).

(1)   For any residential tenancy of less than six months, the landlord shall notify the tenant in writing at least 30 days prior to the
stated termination date of the rental agreement of the landlord’s intent to terminate a periodic tenancy, not renew a fixed-term rental
agreement or increase the rental rate. If the landlord provides insufficient or defective notice or otherwise fails to give the required
written notice, the tenant may remain in the dwelling unit and may retain possession of the dwelling unit for up to 60 days after the date
on which written notice is given to the tenant, regardless of the termination date specified in the notice or in an existing rental agreement.
During such occupancy, the terms and conditions of the tenancy shall be the same as the terms and conditions during the month of
tenancy immediately preceding the notice; provided, however, that if rent was waived or abated in the preceding month or months as part
of the original rental agreement, the rental amount during such 60-day period shall be at the rate established on the last date that a full
rent payment was made.

(2)   For any residential tenancy of six months to three years, the landlord shall notify the tenant in writing at least 60 days prior to
the stated termination date of the rental agreement of the landlord’s intent to terminate a periodic tenancy, not renew a fixed-term rental
agreement or increase the rental rate. If the landlord fails provides insufficient or defective notice or otherwise fails to give the required
written notice, the tenant may remain in the dwelling unit and may retain possession of the dwelling unit for up to 60 days after the date
on which written notice is given to the tenant, regardless of the termination date specified in the notice or in an existing rental agreement.
During such occupancy, the terms and conditions of the tenancy shall be the same as the terms and conditions during the month of
tenancy immediately preceding the notice; provided, however, that if rent was waived or abated in the preceding month or months as part
of the original rental agreement, the rental amount during such 60-day period shall be at the rate established on the last date that a full
rent payment was made.

[D2] Municipal Code of Chicago, Section 5-12-130 (Landlord remedies)
5-12-130 Landlord remedies (part 4 of 4)
(3)   For any residential tenancy greater than three years, the landlord shall notify the tenant in writing at least 120 days prior to the
stated termination date of the rental agreement of the landlord’s intent to terminate a periodic tenancy, not renew a fixed-term rental
agreement or increase the rental rate. If the landlord provides insufficient or defective notice or otherwise fails to give the required
written notice, the tenant may remain in the dwelling unit and may retain possession of the dwelling unit for up to 120 days after the date
on which written notice is given to the tenant, regardless of the termination date specified in the notice or in an existing rental agreement.
During such occupancy, the terms and conditions of the tenancy shall be the same as the terms and conditions during the month of
tenancy immediately preceding the notice; provided, however, that if rent was waived or abated in the preceding month or months as part
of the original rental agreement, the rental amount during such 120-day period shall be at the rate established on the last date that a full
rent payment was made.

(4)   A landlord that seeks to recover possession of a dwelling unit shall wait the specified period a tenant is allowed to remain in the
dwelling unit provided in this Section 5-12-130 before filing any eviction action. If the landlord files an eviction action before the
specified period provided in this Section 5-12-130 has elapsed, then the tenant may raise the insufficient or defective notice, or the
failure to give notice, as a defense to the action, which prohibits the landlord from recovering possession of the dwelling unit until the
specified period has elapsed.
(Prior code § 193.1-13; Added Coun. J. 9-8-86, p. 33771; Amend Coun. J. 11-6-91, p. 7196; Amend Coun. J. 7-22-20, p. 18933, § 3;
Amend Coun. J. 11-24-20, p. 23985, § 3; Amend Coun. J. 4-15-26, p. 42466, § 1)

[D3] Municipal Code of Chicago, Section 5-12-135 (Jackson Park Expanded Fair Notice Pilot Program)
5-12-135 Jackson Park Expanded Fair Notice Pilot Program (part 1 of 2)
(a)   Purpose. The purpose of this section is to establish a pilot program modifying the notice of rental agreement nonrenewal
requirements in order to determine whether modified notice dates affect those in communities experiencing gentrification. The pilot
program shall occur in the areas designated under subsection (c) that are experiencing gentrification. The goals of these modified
requirements are to mitigate the displacement impacts associated with gentrification, better protect the interests of the area’s
economically vulnerable residents from demographic and housing market change, and preserve the economic diversity critical to a
healthy economy.

(b)   Relationship to Residential Landlord Tenant Ordinance. The requirements in this section supersede the notice requirements in
Section 5-12-130(j) within the bounded area listed in subsection (c) of this section during the duration of the pilot listed in subsection (d)
of this section.

(c)   Boun
```
</details>


---

## q063 (docs)

**Question:** What is the proposed 2027 budget for the Chicago Fire Department?

**Reference:** $914,383,396 (proposed).

**Answer:** The proposed 2027 budget for the Chicago Fire Department is $914,383,396 [D1], [D4].

**Judge:** faithful=True, correctness=correct. The system correctly identified the proposed 2027 budget for the Chicago Fire Department matching the reference answer.

<details><summary>Sources</summary>

```
[D1] 2027 Budget Overview (proposed), page 131
2027 Budget Overview (proposed), page 131, Program and Budget Summaries by Department > Public Safety
PUBLIC SAFETY

CHICAGO FIRE DEPARTMENT
The Chicago Fire Department ("CFD") is responsible for the safety of residents and property by providing
emergency services, including extinguishing fires, investigating causes of fires, enforcing the Fire
Prevention Code, and administering emergency medical care. CFD utilizes the latest training methods
and drills to keep Chicago safe from natural and man-made emergencies.
2026 | 2027
FUND SOURCE(S) | FTEs | Appropriation | FTEs Recommendation
Corporate Fund | 4,813 | 808,227,561 | 4,814 | 817,457,251
Chicago Midway Airport Fund | 67 | 11,472,372 | 67 | 11,744,616
Chicago O'Hare Airport Fund | 243 | 42,737,039 | 243 | 43,304,529
Federal Grant Fund | 3 | 29,579,000 | 3 | 27,684,000
Local Public and Private Grant Fund | 25,000 | 586,000
State Grant Fund | 15 | 15,606,000 | 15 | 13,607,000
Total Full-time Equivalent Positions and | 5,141 | $907,646,972 | 5,142 | $914,383,396
Amounts
ALLOCATION
Personnel Services | 831,147,146 | 849,865,865
Non-Personnel Services | 76,499,826 | 64,517,531
2027
Program Summary and Description | FTEs | Funding
ADMINISTRATION | 97 | 34,465,382
FIRE SUPPRESSION AND RESCUE OPERATIONS | 4,065 | 725,634,190
Conducts fire fighting and rescue operations. | Encompasses the
Department's Special Operations and Fire Investigation divisions.
EMERGENCY MEDICAL SERVICES | 837 | 139,153,650
Provides emergency medical care and hospital transport utilizing advanced
life support ("ALS") ambulances, as well as engine companies and fire trucks
equipped with advanced life support equipment.
SUPPORT SERVICES | 57 | 24,210,385
Provides logistical support, including managing the storage, distribution, and
maintenance of supplies, equipment, and departmental technology.
FIRE PREVENTION | 86 | 17,112,548
Inspects schools, institutions, and places of public assembly for compliance
with the City of Chicago Fire Code.
TURNOVER | (26,192,759)

[D2] 2027 Budget Overview (proposed), page 130
2027 Budget Overview (proposed), page 130, Program and Budget Summaries by Department > Public Safety
2026 KEY RESULTS

• Employed 27 interns from Chicago Police and Firefighter Training Academy (CPFTA), One Summer Chicago, and Ladies of Virtue providing immersive, hands-on exposure to careers in the fire service, expanding their knowledge and opportunities for future employment in public safety. • Partnered with the Dept. of Family and Support Services (DFSS) hosting Camp Courage at 7 community sites across Chicago. This three-day, interactive training experience introduced over 249 youth, representing 46 wards, to potential careers in the fire service. • The Mobile Integrated Health Unit (MIH) provided

Proposed Department Budget By Program

3% 2%

4%

15%

FIRE SUPPRESSION AND RESCUE OPERATIONS

EMERGENCY MEDICAL SERVICES

ADMINISTRATION

SUPPORT SERVICES

FIRE PREVENTION

77%

[D3] 2027 Budget Overview (proposed), page 130
2027 Budget Overview (proposed), page 130, Program and Budget Summaries by Department > Public Safety
PUBLIC SAFETY

CHICAGO FIRE DEPARTMENT

over 300 visits in six months across 51 communities in addition to follow-up of over 500 citizen assist calls connecting residents with additional resources and support services • Partnered with OBM and 2FM to sign a capital improvement contract to have a cyclical replacement schedule over the course of 4 years of all aged front- line apparatus. • Trained 43 paramedics in technical rescue to deliver advanced medical care during complex incidents providing high-level, critical life-saving treatment to members of the public and CFD.

KEY FUNCTIONS

• Extinguishes fires that harm life, property, or the environment. • Performs search, rescue, and emergency medical services (EMS). • Provides maritime fire and EMS to a 15-mile limit in Lake Michigan. • Inspects buildings and commercial venues for fire code compliance. • Provides public education on fire awareness and safety. • Detects hazardous materials and mitigates damage to Chicago communities. • Serves as a training hub for northeastern Illinois area fire and police departments. • Participates in the Illinois Mutual Aid Box Alarm System (MABAS), which provides EMS and Fire responses to large scale incidents where mutual aid is necessary.

2027 INITIATIVES

• Expand One Summer Chicago program for interns, Year-Round Summer Youth Employment, and the CPFTA program to increase exposure to careers in the fire service. Continue the partnership with DFSS to expand Camp Courage; a career exploration program for the City’s youth with CFD’s Firefighters and Paramedics. CFD expects 350 will graduate from the program. • Introduce Citizen Academy - Participants will learn about fire safety, emergency preparedness, and basic first aid skills, CPR, how to respond during an emergency, fire prevention, home safety, and ways to protect themselves, their families, and their communities lowering community mortality. • Double Career exploratory program - The CFD Career Exploratory Classes are for residents 18–30 interested in careers in the fire service. Participants learn about firefighting and paramedicine, physical fitness, emergency response, and the hiring process. The program provides hands-on experiences and an opportunity to learn from CFD members preparing participants for a potential career with the Department.

2026 KEY RESULTS

[D4] 2027 Budget Overview (proposed), page 120
2027 Budget Overview (proposed), page 120, Program and Budget Summaries by Department > Public Safety
PUBLIC SAFETY

Public Safety

FUNDING COMPARISON BY DEPARTMENT

Department | 2026 | 2027
Office of Public Safety Administration | 138,658,676 | 134,809,636
Chicago Police Board | 498,200 | 496,322
Chicago Police Department | 2,121,127,600 | 2,243,691,824
Office of Emergency Management and Communications | 101,398,120 | 105,385,714
Chicago Fire Dep
```
</details>


---

## q069 (docs)

**Question:** What does section 14X-8-803.7 require?

**Reference:** Cooling and dehumidification equipment, where provided, must be properly installed and maintained in safe working condition (14X-8-803.7).

**Answer:** Section 14X-8-803.7 requires that cooling and dehumidification equipment, where provided, must be properly installed, maintained in a safe working condition, and capable of performing its intended function [D1].

**Judge:** faithful=True, correctness=correct. The system's answer accurately captures the requirements specified in section 14X-8-803.7 according to the source.

<details><summary>Sources</summary>

```
[D1] Municipal Code of Chicago, Section 14X-8-803.7 (Maintenance)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.7 Maintenance
Cooling and dehumidification equipment, where provided, must be properly installed and maintained in a safe working condition and
capable of performing the intended function.
(Added Coun. J. 6-22-22, p. 49372, § 7)

[D2] Municipal Code of Chicago, Section 14X-8-803.1 (Scope)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.1 Scope
Existing buildings must be provided with cooling and dehumidification equipment as required by Sections 14X-8-803.2 through 14X-8-
803.5. The equipment required by this section must be operated as required by Section 14X-8-803.6.
(Amend Coun. J. 6-22-22, p. 49372, § 7)

[D3] Municipal Code of Chicago, Section 14X-8-803.5 (Performance)
14X-8-803 Cooling and dehumidification equipment > 14X-8-803.5 Performance
Cooling and dehumidification equipment required by Sections 14X-8-803.2 through 14X-8-803.4 must be independent of heating
equipment or be capable of switching from heating to cooling mode within one hour.
(Added Coun. J. 6-22-22, p. 49372, § 7)

[D4] Municipal Code of Chicago, Section 14X-8-801.3 (Maintenance)
14X-8-801 General > 14X-8-801.3 Maintenance
Heating, cooling, and mechanical systems and equipment must be maintained in proper operating condition in accordance with the
original design. Heating, cooling, and mechanical equipment must be maintained and operated in a safe and sanitary condition. Devices
or safeguards that were required by law or the manufacturer's instructions at the time of installation must be maintained in compliance
with those requirements. To determine compliance with this chapter, the building official may require a condition report in accordance
with Section 14X-1-104.
(Added Coun. J. 6-17-26, p. 45214, Art. IV, § 43)

[D5] Municipal Code of Chicago, Section 14X-8-801.2 (Measurement)
14X-8-801 General > 14X-8-801.2 Measurement
For determining compliance with this section, room temperature and relative humidity are to be measured 3 feet (914 mm) above the
floor and at least 3 feet (914 mm) away from any exterior wall.
(Added Coun. J. 6-22-22, p. 49372, § 7)
```
</details>


---

## q075 (both)

**Question:** How many water in basement complaints were made in 2026, and what is the proposed 2027 budget for the Department of Water Management?

**Reference:** 6,915 complaints in 2026 (to 2026-11-18); the proposed budget is $783,350,165.

**Answer:** There were 6,912 water in basement complaints recorded in 2026, based on data available through 2026-11-18 [T1]. The proposed 2027 budget for the Department of Water Management is $783,350,165 [D4].

**Judge:** faithful=True, correctness=correct. The system correctly identified both the number of water in basement complaints and the proposed 2027 budget for the Department of Water Management, matching the reference answer closely.

<details><summary>Sources</summary>

```
[T1] City data tables. Question asked: How many water in basement complaints were made in 2026?
SQL: SELECT COUNT(*) FROM service_requests_311 WHERE sr_short_code = 'AAF' AND NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry') AND created_date >= '2026-01-01' AND created_date < '2027-01-01' LIMIT 500
Columns: count
6912
(1 rows)
Code-checked note: The data ends on 2026-11-18, so the period asked about is only covered up to that date.
Note from the query writer: Counted 'AAF' (Water in Basement Complaint) requests
Note from the query writer: Duplicates excluded
Note from the query writer: City-generated requests (Mass Entry, Generated In House) excluded
Note from the query writer: Date range 2026-01-01 to 2026-11-18 (data end date)

[D1] 2027 Budget Overview (proposed), page 115
2027 Budget Overview (proposed), page 115, Program and Budget Summaries by Department > Infrastructure Services
INF RASTRUCTURE SERVICES

DEPARTMENT OF WATER MANAGEMENT
Commissioner's Office
The Department of Water Management ("DWM") is responsible for the delivery of water to Chicago
residents and suburban communities. DWM also transmits wastewater from homes and businesses
along with storm water runoff from streets to the Water Reclamation system. Operations rely on a
network of purification plants, tunnels, pumping stations, structures, and water and sewer mains.
2026 | 2027
FUND SOURCE(S) | FTEs | Appropriation | FTEs Recommendation
Water Fund | 83 | 16,195,656 | 83 | 17,453,524
Sewer Fund | 0 | 1,500,000
Entitlement Fund | 13,392,000 | 18,224,000
Total Full-time Equivalent Positions and | 83 | $29,587,656 | 83 | $37,177,524
Amounts
ALLOCATION
Personnel Services | 7,153,150 | 7,286,618
Non-Personnel Services | 22,434,506 | 29,890,906
2027
Program Summary and Description | FTEs | Funding
ADMINISTRATION | 20 | 4,597,668
SAFETY AND SECURITY | 63 | 14,879,148
Coordinates employee safety measures and provides site security at water
and sewer system facilities.
SYSTEM MAINTENANCE | 18,224,000
Maintains and repairs sewer mains, catch basins, and manholes to ensure
the free flow of storm and sanitary sewage and to prevent hazards to the
public. Performs normal and emergency repair and maintenance of water
distribution appurtenances.
TURNOVER | (523,292)

Bureau of Administrative Support
2026 | 2027
FUND SOURCE(S) | FTEs | Appropriation | FTEs Recommendation
Water Fund | 55 | 6,583,518 | 60 | 7,323,818
ALLOCATION
Personnel Services | 5,644,182 | 6,384,482
Non-Personnel Services | 939,336 | 939,336
2027
Program Summary and Description | FTEs | Funding
ADMINISTRATION | 60 | 7,681,075
TURNOVER | (357,257)

[D2] 2027 Budget Overview (proposed), page 114
2027 Budget Overview (proposed), page 114, Program and Budget Summaries by Department > Infrastructure Services
INF RASTRUCTURE SERVICES

DEPARTMENT OF WATER MANAGEMENT

service line replacements, facility upgrades and improvements, meter replacements, and restoration • Received $2M in federal earmarks from Senator Durbin administered through United States Environmental Protection Agency (USEPA) for daycare lead service line replacements (focus will be replacements in low- income neighborhoods) • Received $9.9M in Water Infrastructure Improvements for the Nation (WIIN) grant funding administered by USEPA that will be used for block-level lead service line replacements in the Austin community • Completed 8,000 lead service line replacements across the City. • Started a downspout disconnection initiative to help alleviate flooding in the Chatham community

KEY FUNCTIONS

• Collects, purifies, tests, and distributes almost one billion gallons daily of fresh, clean, safe drinking water to Chicago and 120 suburbs. • Provides capital improvement engineering services for the design and construction of new water and sewer mains. • Operates, maintains, and repairs the City’s water and combined sewer systems comprised of two of the world’s largest water purification plants, 12 pumping stations, 4,244 miles of water mains, 48,064 hydrants, 4,480 miles of sewer and storm water mains, and 353,000 structures and manholes. • Operates an EPA-certified Chemistry Lab, IDPH- certified Microbiology Lab, and two 24/7 Control Laboratories to analyze samples for regulatory compliance. • Develops and operates lead testing and Lead Service Line Replacement (LSLR) programs as the Registered Operator in Charge according to IEPA and IDPH regulations.

2027 INITIATIVES

• Execute a Maintenance, Repair, and Operations (MRO) agreement with Grainger through a Cook County reference contract to substantially streamline materials procurements. • Complete 12,000 lead service line replacements citywide. • Secure ownership of land from IDOT for electrical improvements needed for Cermak Pumping Station. • Pilot lead service line replacements with the People’s Gas pipe retirement program to lower restoration costs and reduce construction impacts to residents. • Complete 10-year Condition Assessments for both purification plants and 11 pumping stations. • Complete meter replacement of all suburban wholesale customers (needed for 2030 Cost of Service transition).

2026 KEY RESULTS

[D3] 2027 Budget Overview (proposed), page 119
2027 Budget Overview (proposed), page 119, Program and Budget Summaries by Department > Infrastructure Services
INF RASTRUCTURE SERVICES

Bureau of Meter Services
2026 | 2027
FUND SOURCE(S) | FTEs | Appropriation | FTEs Recommendation
Water Fund | 116 | 13,281,584 | 117 | 13,604,452
ALLOCATION
Personnel Services | 12,307,834 | 12,630,702
Non-Personnel Services | 973,750 | 973,750
2027
Program Summary and Description | FTEs | Funding
ADMINISTRATION | 2 | 557,152
METER OPERATIONS SUPPORT | 39 | 4,278,948
Supports the City's water meter installation and repair programs.
WATER METER MANAGEMENT | 76 | 9,404,034
Provides water meters to customers. Repairs meters, including remote
meters with read-out devices in the field. Reconditions and tests newly
designed meters, fire detector
```
</details>
