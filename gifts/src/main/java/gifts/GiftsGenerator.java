package gifts;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.math3.random.JDKRandomGenerator;

import people.Group;
import people.Member;

/**
 * Classe de generation du mapping entre participants
 * 
 * @author Vincent
 */
public class GiftsGenerator {
	/** Liste des participants au tirage au sort */
	final ArrayList<Member> sample;
	/** Ensemble des groupes concernes */
	final ArrayList<Group> groups;

	/**
	 * Constructeur principal de la classe. Il initialise simplement les listes.
	 */
	public GiftsGenerator() {
		sample = new ArrayList<Member>();
		groups = new ArrayList<Group>();
	}

	/**
	 * Ajout d'un participant, et mise a jour des groupes eventuellement concernes.
	 * 
	 * @param m membre a ajouter
	 */
	public void addMember(Member m) {
		sample.add(m);
		if (!groups.contains(m.getGroup())) {
			groups.add(m.getGroup());
		}
	}

	/**
	 * Ajout multiple de participants.
	 * 
	 * @param m membres a ajouter (separes par des virgules)
	 */
	public void addMembers(Member... m) {
		for (Member mi : m) {
			addMember(mi);
		}
	}

	/**
	 * Generation du mapping entre les participants.
	 * 
	 * @return Map "donneur"=>"receveur"
	 */
	@SuppressWarnings("unchecked")
	public Map<Member, Member> generateList() {
		// Liste des personnes ayant deja recu un cadeau
		List<Member> given = new ArrayList<Member>(sample.size());
		// mapping a completer
		Map<Member, Member> mapping = new HashMap<Member, Member>();
		// Generateur de nombre aleatoires.
		final JDKRandomGenerator g = new JDKRandomGenerator();
		// Tri des groupes par taille
		groups.sort(null);
		/*
		 * On parcourt les groupes en commencant par le plus petit. Cela assure que les plus petit groupes ne s'offrent
		 * pas de cadeaux entre eux.
		 */
		for (Group gr : groups) {
			List<Member> groupMembers = gr.getMembers();
			// On traite les membres dans l'ordre
			for (Member m1 : groupMembers) {
				// On part de la liste de tous les participants
				List<Member> s = (List<Member>) sample.clone();
				/*
				 * Suppression des conjoints, de ceux qui ont deja eu un cadeau, et de ceux ayant offert le cadeau (pour
				 * eviter les aller/retours)
				 */
				clear(s, m1, given);
				// Si possible, on evite les personnes du meme groupe.
				s.removeAll(groupMembers);
				// Sinon, on est obliges d'offrir a quelqu'un du meme groupe.
				if (s.isEmpty()) {
					s.addAll(groupMembers);
					clear(s, m1, given);
				}
				/*
				 * Si les seules personnes devant encore recevoir un cadeau sont le conjoint ou celui qui a offert
				 * directement le cadeau à la personne, on relance le tirage.
				 */
				if (s.isEmpty()) {
					return generateList();
				}
				// Tirage aleatoire dans la liste des "receveurs" potentiels
				int i = g.nextInt(s.size());
				Member m2 = s.get(i);
				// On indique que m1 a offert a m2, on ajoute donc m1 aux exclusions de m2
				m2.exclude(m1);
				given.add(m2);
				mapping.put(m1, m2);
			}

		}
		return mapping;
	}

	/**
	 * Suppression dans la liste du conjoint, des personnes exclues, et de ceux qui ont deja recu un cadeau.
	 * 
	 * @param s liste a traiter
	 * @param m participant devant offrir un cadeau
	 * @param given liste des participants ayant deja recu un cadeau.
	 */
	private void clear(List<Member> s, Member m, List<Member> given) {
		if (m.getPartner() != null) {
			s.remove(m.getPartner());
		}
		s.removeAll(m.getExclusions());
		s.removeAll(given);
	}
}
