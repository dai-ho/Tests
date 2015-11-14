package gifts;

import java.util.Map;
import java.util.Set;

import people.Group;
import people.Member;

public class GiftsMainTest {

	public static void main(String[] args) {
		GiftsGenerator gen = new GiftsGenerator();
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

		gen.addMembers(marine, vincent, estelle, nicolas, virginie, thomas, annelise, sebastien, pierre, dany, flore, manuel);

		Map<Member, Member> result = gen.generateList();

		Set<Member> keys = result.keySet();
		for (Member m : keys) {
			System.out.println(m.getName() + " offre un cadeau à " + result.get(m).getName());
		}
	}

}
