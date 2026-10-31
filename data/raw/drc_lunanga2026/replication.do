***********************************************************************************
*** What 	: Replication file for "From Demand Deficit to Development Strategy:
***			  Navigating Mini-Grid Viability in a Fragile Context"
***			  by Elie Lunanga, Nik Stoop, Marijke Verpoorten, Sebastien Desbureaux
***			  Revised & resubmitted to Energy Economics
*** Version : January 2026
*** Contact : nik.stoop@uantwerp.be
***********************************************************************************

clear all
set more off

*** Optionally set scheme for graph aesthetics
capture set scheme lean1

*** If not already installed, optionally install this user-written command used to combine graphs.
*** It only affects the presentation of the figures but not the underlying results. 
*** Each component figure can be replicated independently without this command. 
capture which grc1leg
if _rc {
net install grc1leg, from("http://www.stata.com/users/vwiggins") replace
}

*** Replace "SET YOUR DIRECTORY by the directory where you store the replication folder 
cap cd "SET YOUR DIRECTORY"
	

*********************************************************	
*** The below code reproduces the Figures and Tables ****
*********************************************************	

*** FIGURE 1. Study area ==> this map is manually created by the authors in QGIS, it is not reproduced in this do-file. 

*** FIGURE 2. Census data ==> this map is manually created by the authors in QGIS, it is not reproduced in this do-file. 

*** FIGURE 3. Evolution of connection rates and clients 

	use "data/electricity1.dta",clear

	* connection rates 		
	twoway (line rate months_grid if area==3, sort) (line rate months_grid if area==1, sort lcolor(green)) (line rate months_grid if area==2, sort lcolor(red)), ytitle("Connection rate (%)") ylabel(0(5)75, labsize(small)) xtitle("Months since grid installation", size(medsmall)) xlabel(0(6)66, labsize(small) angle()) legend(off) subtitle("Panel A: connection rates") 
	graph export "figures/fig3A.pdf", replace
	
	* household clients 
	twoway (line clients_hh months_grid if area==3,sort) (line clients_hh months_grid if area==1, sort lcolor(green)) (line clients_hh months_grid if area==2, sort lcolor(red)), ytitle("Nr. of connected clients") ylabel(0(1000)11000, labsize(small) format(%9.0fc)) xtitle("Months since grid installation", size(medsmall)) xlabel(0(6)66, labsize(small) angle()) subtitle("Panel B: Household clients") legend(order(1 "Mutwanga" 2 "Goma" 3 "Lubero") position(6) size(medsmall) rows(1))
	graph save fig3B.gph, replace 

	* SME clients 
	twoway (line clients_sme months_grid if area==3,sort) (line clients_sme months_grid if area==1, sort lcolor(green)) (line clients_sme months_grid if area==2, sort lcolor(red)), ytitle("Nr. of connected clients") ylabel(0(20)380, labsize(small) format(%9.0fc)) xtitle("Months since grid installation", size(medsmall)) xlabel(0(6)66, labsize(small) angle()) subtitle("Panel C: SME clients") legend(order(1 "Mutwanga" 2 "Goma" 3 "Lubero") position(6) size(medsmall) rows(1))
	graph save fig3C.gph, replace 
	
	* combining panels B and C
	grc1leg fig3B.gph fig3C.gph, legendfrom(fig3B.gph) position(6) row(1)
	graph export "figures/fig3BC.pdf", replace
	erase fig3B.gph
	erase fig3C.gph
	

*** FIGURE 4: Average monthly electricity consumption 

	use "data/electricity1.dta",clear
	
	* Household clients
	twoway (line kwh_month_av_hh months_grid if area==3, sort) (line kwh_month_av_hh months_grid if area==1, sort lcolor(green)) (line kwh_month_av_hh months_grid if area==2, sort lcolor(red)), ytitle("kWh consumption", size(medsmall)) ylabel(#10, labsize(small)) xtitle("Months since grid installation") legend(order(1 "Mutwanga" 2 "Goma" 3 "Lubero")) xlabel(0(6)66, labsize(small) angle()) subtitle("Panel A: Household clients")	
	graph save fig4A.gph,replace
			
	* SME clients 
	twoway (line kwh_month_av_sme months_grid if area==3, sort) (line kwh_month_av_sme months_grid if area==1, sort lcolor(green)) (line kwh_month_av_sme months_grid if area==2, sort lcolor(red)), ytitle("kWh consumption", size(medsmall)) ylabel(#10, labsize(small)) xtitle("Months since grid installation") legend(order(1 "Mutwanga" 2 "Goma" 3 "Lubero")position(6) size(medsmall) rows(1)) xlabel(0(6)66, labsize(small) angle()) subtitle("Panel B: SME clients")		
	graph save fig4B.gph,replace
	
	* combining both panels 
	grc1leg fig4A.gph fig4B.gph, legendfrom(fig4B.gph) position(6) row(1)
	graph export "figures/fig4.pdf", replace
	erase fig4A.gph
	erase fig4B.gph

   
*** FIGURE 5: Heterogeneity in monthly electricity consumption 
	
	use "data/electricity2.dta",clear

		graph box kwh_client_av if client==1, over(area) nooutsides medtype(cline) medline(lcolor(red)) ytitle("Average monthly kWh") ytitle(, size(medsmall))	note("") subtitle("Panel A: Households, excluding outliers") ylabel(0(10)105, nogrid) 
		graph save fig5A, replace 
		
		graph box kwh_client_av if client==1, over(area) medtype(cline) medline(lcolor(red)) ytitle("Average monthly kWh") ytitle(, size(medsmall))	subtitle("Panel B: Households, including outliers") ylabel(0(200)1850, nogrid)
		graph save fig5B, replace 	
		
graph box kwh_client_av if client==2, over(area) nooutsides medtype(cline) medline(lcolor(red)) ytitle("Average monthly kWh") ytitle(, size(medsmall))	note("") subtitle("Panel C: SMEs, excluding outliers") ylabel(0(100)1110, nogrid)
		graph save fig5C, replace 
		
		graph box kwh_client_av if client==2, over(area) medtype(cline) medline(lcolor(red)) ytitle("Average monthly kWh") ytitle(, size(medsmall))	subtitle("Panel D: SMEs, including outliers") ylabel(0(500)4700, nogrid)
		graph save fig5D, replace 
		
		graph combine fig5A.gph fig5B.gph fig5C.gph fig5D.gph
		graph export "figures/fig5.pdf", replace
		erase fig5A.gph
		erase fig5B.gph		
		erase fig5C.gph		
		erase fig5D.gph	
		
		
*** FIGURE 6: Total monthly electricity consumption
 
	use "data/electricity1.dta",clear

	* Goma
	twoway (line kwh_month_tot_hh ym if area==1, sort) (line kwh_month_tot_sme ym if area==1, sort), ytitle("Total kWh", size(medsmall)) ylabel(#10, labsize(small) format(%9.0fc)) xtitle(" ") legend(order(1 "Households" 2 "SMEs")position(6) size(medsmall) rows(1)) xlabel(708(12)783, labsize(small) angle()) subtitle("Panel A: Goma")
	graph export "figures/fig6A.pdf", replace
	
	* Mutwanga and Lubero 
	twoway (line kwh_month_tot_hh ym if area==3, sort) (line kwh_month_tot_hh ym if area==2, sort lcolor(red)) (line kwh_month_tot_sme ym if area==3, sort) (line kwh_month_tot_sme ym if area==2, sort lcolor(green)), ytitle("Total kWh", size(medsmall)) ylabel(#10, labsize(small) format(%9.0fc)) xtitle(" ") legend(order(1 "Mutwanga households" 2 "Lubero households" 3 "Mutwanga SMEs" 4 "Lubero SMEs") position(6) size(medsmall) rows(2)) xlabel(708(12)783, labsize(small) angle()) subtitle("Panel B: Mutwanga and Lubero") 
	graph export "figures/fig6B.pdf", replace
 
	* drop in consumption in January 21 in Mutwanga 
	di 1-(4078.9/22394.2) // 82% HHs
	di 1-(1651.6/9023.7) // 82% SMEs 
	

*** FIGURE 7: Impact of conflict shocks on electricity consumption 
	
	* Panel A
		use "data/electricity1.dta",clear
		* keep relevant months and area 
		keep if ym>719
		keep if ym<756
		keep if area==3
		
		* normalize consumption at Nov.2020 - prior to ADF attacks
		gen kwh_hhnorm=(kwh_month_tot_hh/22394.2)*100
		gen kwh_smenorm=(kwh_month_tot_sme/9023.7)*100	

		twoway (line kwh_hhnorm ym, sort) (line kwh_smenorm ym, sort) , ytitle("Normalised consumption", size(small)) ylabel(#10, labsize(small) format(%9.0fc)) xtitle("Year month") legend(order(1 "Households" 2 "SMEs" ) size(small) rows(2)) xlabel(720(2)755, labsize(small) angle(forty_five)) subtitle("Panel A: Mutwanga") xline(731, lpattern(dash)) yline(18, lpattern(dot) lcolor(gs12)) text(20 733 "{bf:-82%}", place(ne) size(small) color(black))
		
		graph save fig7a.gph, replace 

	* Panel B 
		use "data/electricity3.dta",clear
		
		twoway (line kwh_hhnorm yrmth, sort) (line kwh_smenorm yrmth, sort), xlabel(768(1)789, labsize(small) angle(forty_five)) xtitle("Year month") ytitle("Normalised consumption",size(small)) ylabel(#10, labsize(small) format(%9.0fc)) subtitle("Panel B: Goma") xline(780, lpattern(dash)) legend(order(1 "Households" 2 "SMEs") size(small) rows(2)) yline(77 87, lpattern(dot) lcolor(gs12)) text(88.5 780.5 "{bf:-13%}", place(e) size(small) color(black)) text(77.5 780.5 "{bf:-23%}", place(e) size(small) color(black))
		graph save fig7b.gph, replace 
	
	
	* combining panels A and B
		grc1leg fig7a.gph fig7b.gph, legendfrom(fig7a.gph) ycommon 
		graph export "figures/fig7.pdf", replace
		erase fig7a.gph
		erase fig7b.gph	

	
 
*** TABLE 1: Describing the sample
	
	*** PANEL A: households
	use "data/survey.dta",clear
	drop if firm==1
	* demographics 
	sum male age education hhsize depratio [aw=weight] 
	* energy profile 
	sum solar appliances energy_exp [aw=weights] 
	* wealth
	sum income parcel_own good_qual [aw=weights] 
	* geographic 
	sum distance_plus50m [aw=weights]	
	* connection 
	sum connected [aw=weights]
	* consumption 
	sum kwh [aw=weights]

	
	*** PANEL B: small businesses
	use "data/survey.dta",clear
	drop if firm==0
	* demographics
	sum male age education employment [aw=weights] 
	* energy profile
	sum solar generator appliances energy_exp [aw=weights] 
	* wealth
	sum sales parcel_own good_qual [aw=weights] 
	* geographic
	sum distance_plus50m [aw=weights]
	* connection
	sum connected [aw=weights]
	* consumption 
	sum kwh [aw=weights]


*** TABLE 2: Household electricity uptake and consumption

	use "data/survey.dta",clear
	drop if firm==1
	eststo clear
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust
	eststo: reg kwhln male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust 
	esttab using "tables/table2.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table 2") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)	


*** TABLE 3: Small business electricity uptake and consumption

	use "data/survey.dta",clear
	drop if firm==0
	eststo clear
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust
	eststo: reg kwhln male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust
	esttab using "tables/table3.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table 3") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)		
	
	
*** TABLE 4: Why not (yet) connected?

	use "data/survey.dta",clear
	tab firm client_future,row
	tab firm nomoney,row 
	tab firm renting,row
	
	
************************
* Appendix A. Sampling *
************************
	
	* Table A1: Households and businesses by area 
	
		* for census columns
		use "data/census.dta",clear 
			tab firm if area==3 // Mutwanga
			tab firm if area==1 // Goma
			tab firm if area==2 // Lubero
	
		* for sample columns
		use "data/survey.dta",clear
			tab firm if area==3 // Mutwanga
			tab firm if area==1 // Goma
			tab firm if area==2 // Lubero
	
	* Table A2: Sample weights
		
		* for census columns
		use "data/census.dta",clear 
			bysort firm: tab constr_qual 
		
		* for sample columns
		use "data/survey.dta",clear
			
			* unweighted
			bysort firm: tab constr_qual 
			
			* weighted 
			bysort firm: tab constr_qual [aw=weights]
	
	

********************************
* Appendix B. Electricity data *
********************************	
	
	* Table A3: Clients by research area 
	use "data/electricity2.dta",clear
		
		* households
		tab area if client==1
		
		* SMEs
		tab area if client==2
		
		* Total number 
		tab area 
		
		* % of SMEs 
		bysort area: tab client
		tab client
		
	
	* Table A4: Average monthly electricity consumption 
	use "data/electricity1.dta",clear
	
		* Households
		sum kwh_month_av_hh if area==3 // Mutwanga
		sum kwh_month_av_hh if area==1 // Goma 
		sum kwh_month_av_hh if area==2 // Lubero 
		
		* SMEs 
		sum kwh_month_av_sme if area==3 // Mutwanga
		sum kwh_month_av_sme if area==1 // Goma 
		sum kwh_month_av_sme if area==2 // Lubero 
	
	

************************
* Appendix C. Attrition *
************************
	
	* Table A5: Survey attrition
	use "data/survey.dta",clear
				
		* nr. of HHs and firms at baseline, by area 
		tab firm 			// Total
		tab firm if area==3 // Mutwanga
		tab firm if area==1 // Goma
		tab firm if area==2 // Lubero
		
		* nr. of HHs and firms at follow-up, by area 
		tab firm 		   if attrition==0 // Total
		tab firm if area==3 & attrition==0 // Mutwanga
		tab firm if area==1 & attrition==0 // Goma
		tab firm if area==2 & attrition==0 // Lubero
		
		* attrition percentages by HHs/firms and area
			
			* Total 
			sum attrition if firm==0 
			sum attrition if firm==1
			
			* Mutwanga
			sum attrition if firm==0 & area==3
			sum attrition if firm==1 & area==3
			
			* Goma 
			sum attrition if firm==0 & area==1
			sum attrition if firm==1 & area==1
			
			* Lubero 
			sum attrition if firm==0 & area==2
			sum attrition if firm==1 & area==2		
		
		
	* Table A6: Electricity uptake among households 
	use "data/survey.dta",clear
	drop if firm==1
	eststo clear
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights] if attrition==0,robust
	esttab using "tables/tableA6.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A6") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)	
	
	
	* Table A7: Electricity uptake among SMEs
	use "data/survey.dta",clear
	drop if firm==0	
	eststo clear
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust	
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights] if attrition==0, robust	
	esttab using "tables/tableA7.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A7") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)		
			
	

******************************************
* Appendix D. Alternative specifications *
******************************************	
	
	
	* Table A8: Electricity uptake among households 
	use "data/survey.dta",clear
	drop if firm==1
	eststo clear
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.enumerator [pw=weights],robust
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust
	logit connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust
	eststo: margins, dydx(*) post
	probit connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust
	eststo: margins, dydx(*) post
	esttab using "tables/tableA8.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A8") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)	

	
	* Table A9: Electricity uptake among SMEs
	use "data/survey.dta",clear
	drop if firm==0	
	eststo clear
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.enumerator i.sector [pw=weights], robust	
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust	
	logit connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust	
	eststo: margins, dydx(*) post
	probit connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust	
	eststo: margins, dydx(*) post
	esttab using "tables/tableA9.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A9") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)		
	
	
	* Table A10: Electricity consumption among connected households
	use "data/survey.dta",clear
	drop if firm==1
	eststo clear
	eststo: reg kwhln male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.enumerator [pw=weights],robust
	eststo: reg kwhln male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m i.area i.enumerator [pw=weights],robust 
	esttab using "tables/tableA10.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A10") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)			
	
	
	* Table A11: Electricity consumption among connected SMEs
	use "data/survey.dta",clear
	drop if firm==0
	eststo clear
	eststo: reg kwhln male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.enumerator i.sector [pw=weights], robust
	eststo: reg kwhln male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m i.area i.enumerator i.sector [pw=weights], robust
	esttab using "tables/tableA11.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A11") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps  drop(*.enumerator _cons)			
	

	
******************************************
* Appendix E. Conflict Exposure *
******************************************	

	* Figure A1 Reported conflict exposure 
		use "data/survey.dta",clear
		eststo clear

		forvalues x=1(1)9{
		gen x_`x'=0
		}
		
		* with labels
		graph hbar (mean) x_1 x_2 x_3 x_4 x_5 x_6 x_7 x_8 x_9 , ascategory legend(off) ylabel(0(0)0, noticks nogrid labcolor(white)) yvar(relabel(1"{bf:Exposure to any of the below}" 2"{it:Displacement by armed combat}" 3"{it:Robbery}" 4"{it:Household member killed}" 5"{it:Witnessed murder or rape}" 6"{it:Forced labor}" 7"{it:Injury due to armed conflict }" 8"{it:Abduction}" 9"{it:Sexual violence}") label(labsize(small)))  plotregion(margin(zero)) ysize(6) xsize(5) ytitle(" ") title(" ") plotregion(lcolor(none) fcolor(white) margin(zero)) graphregion(lcolor(white) fcolor(white)) yscale(noline)  
		drop x_1 x_2 x_3 x_4 x_5 x_6 x_7 x_8 x_9
		graph save g0, replace 
		
		* all the other plots, without labels
		graph hbar (mean) conflict_exposure violence2 violence1 violence7 violence5 violence3 violence4 violence6 violence8 , ascategory legend(off) blabel(bar,format(%9.2f)) ylabel(0(0.2)0.85) ytitle("proportion of respondents") yvar(relabel(1" " 2" " 3" " 4" " 5" " 6" " 7" " 8" " 9" ")) title("{bf:A. 1994 to baseline}", size(small)) plotregion(margin(zero)) ysize(6) xsize(5)

		graph save g1, replace 	
		
		graph hbar (mean) conflict12m violence2_an violence1_an violence7_an violence5_an violence3_an violence4_an violence6_an violence8_an , ascategory legend(off) blabel(bar,format(%9.2f)) ylabel(0(0.2)0.85) ytitle("proportion of respondents") yvar(relabel(1" " 2" " 3" " 4" " 5" " 6" " 7" " 8" " 9" "))  title("{bf:B. 12 months before baseline}", size(small)) plotregion(margin(zero)) ysize(6) xsize(5)
		graph save g2, replace 
		
		graph hbar (mean) conflict19 violence2_19 violence1_19 violence7_19 violence5_19 violence3_19 violence4_19 violence6_19 violence8_19, ascategory legend(off) blabel(bar,format(%9.2f)) ylabel(0(0.2)0.85) ytitle("proportion of respondents") yvar(relabel(1" " 2" " 3" " 4" " 5" " 6" " 7" " 8" " 9" ")) title("{bf:C. Baseline to follow-up}", size(small)) plotregion(margin(zero)) ysize(6) xsize(5)
		graph save g3, replace 
		
		* combine them 
		graph combine g0.gph g1.gph g2.gph g3.gph,  row(1) imargin(zero) // title("{bf:Exposure to different violent events}", size(medium))
		gr_edit plotregion1.graph1.grpaxis.style.editstyle linestyle(color(white)) editcopy		
		erase g0.gph 
		erase g1.gph 
		erase g2.gph 
		erase g3.gph	

		
		
	* Figure A2, Panel A: Reported conflict exposure by location 
		use "data/survey.dta",clear
		eststo clear	

		graph hbar (mean) conflict_exposure conflict12m conflict19, over(area, relabel(1 "{bf:Goma: }" 2 "{bf:Lubero: }" 3 "{bf:Mutwanga: }")) ascategory ytitle("proportion of respondents") yvar(relabel(1"{it:1994 to baseline}" 2"{it:12 months before baseline}" 3"{it:Baseline to follow-up}")) blabel(bar,format(%9.2f)) ylabel(0(0.2)0.9) title("Panel A: Reported conflict exposure by location") ysize(7) xsize(12)

	
	
	* Figure A2, Panel B: Monthly ACLED conflict events
		use "data/acled.dta",clear
		eststo clear		
		twoway (line conflict_n yrmth if id==1, sort lcolor(red)) (line conflict_n yrmth if id==4, sort) (line conflict_n yrmth if id==3, sort lcolor(green)) , xlabel(707(6)778, angle(forty_five)) legend(order(1 "Beni" 2 "Lubero" 3 "Goma"))  xtitle("Year month") ytitle("Total conflict events") title("Panel B: Monthly ACLED conflict events")
	


	* Table A12: HHs 
	use "data/survey.dta",clear
	drop if firm==1
	eststo clear
	eststo: reg connected male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m conflict12m i.area i.enumerator [pw=weights],robust
	eststo: reg kwhln male age education hhsize depratio solar appliances energy_expln incomeln parcel_own good_qual distance_plus50m conflict19 i.area i.enumerator [pw=weights],robust 
	esttab using "tables/tableA12.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A12") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)	


	* Table A13: SMEs
	use "data/survey.dta",clear
	drop if firm==0
	eststo clear
	eststo: reg connected male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m conflict12m i.area i.enumerator i.sector [pw=weights], robust
	eststo: reg kwhln male age education employment solar generator appliances energy_expln salesln parcel_own good_qual distance_plus50m conflict19 i.area i.enumerator i.sector [pw=weights], robust
	esttab using "tables/tableA13.rtf", replace star(* 0.10 ** 0.05 *** 0.01) b(3) se(3) label title("Table A13") r2 nonotes addnotes("*** p<0.01, ** p<0.05, * p<0.1; Robust standard errors presented between brackets.") nogaps drop(*.enumerator _cons)		
	



*** END ***	

	
	

	