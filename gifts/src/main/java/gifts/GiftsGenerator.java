package gifts;

import java.util.List;
import java.util.Map;
import java.util.Set;

import people.Group;
import people.Member;

public class GiftsGenerator {

	public static void main(String[] args) {
		GiftsFactory f = new GiftsFactory();
		Group convert = new Group();
		Group ruch = new Group();
		Member vincent = new Member("Vincent", ruch);
		Member marine = new Member("Marine", convert);
		Member estelle = new Member("Estelle", ruch);
		Member nicolas = new Member("Nicolas", ruch);
		Member virginie = new Member("Virginie", convert);
		Member thomas = new Member("Thomas", convert);
		Member annelise = new Member("Anne-Lise", convert);
		Member sebastien = new Member("Sebastien", convert);
		Member pierre = new Member("Pierre", convert);
		Member dany = new Member("Dany", convert);
		Member manuel = new Member("Manuel", ruch);
		Member flore = new Member("Flore", ruch);

		vincent.setPartner(marine);
		estelle.setPartner(nicolas);
		virginie.setPartner(thomas);
		annelise.setPartner(sebastien);
		pierre.setPartner(dany);
		flore.setPartner(manuel);

		// f.addMember(marine);
		// f.addMember(vincent);
		// f.addMember(estelle);
		// f.addMember(nicolas);
		// f.addMember(virginie);
		// f.addMember(thomas);
		// f.addMember(annelise);
		// f.addMember(sebastien);
		// f.addMember(pierre);
		// f.addMember(dany);
		// f.addMember(flore);
		// f.addMember(manuel);

		f.addMembers(marine, vincent, estelle, nicolas, virginie, thomas, annelise, sebastien, pierre, dany, flore, manuel);

		Map<Member, Member> result = f.generateList2();

		Set<Member> keys = result.keySet();
		for (Member m : keys) {
			System.out.println(m.getName() + " offre un cadeau à " + result.get(m).getName());
		}
	}

}
