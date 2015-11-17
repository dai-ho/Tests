package fr.free.hd.ruch.giftsrandomizer.people;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Groupe representant par exemple une famille. Il s'agit basiquement d'une liste de participants.
 * 
 * @author Vincent
 */
public class Group implements Comparable<Group>, Comparator<Group> {

	final String name;

	/** Membres du groupe */
	final private List<Member> members;

	/**
	 * Constructeur de base.
	 */
	public Group(String name) {
		this.name = name;
		members = new ArrayList<Member>();
	}

	public String getName() {
		return name;
	}

	/**
	 * Ajout d'un membre au groupe.
	 * 
	 * @param m membre a ajouter
	 */
	public void addMember(Member m) {
		members.add(m);
	}

	/**
	 * Nombre de personnes dans le groupe
	 * 
	 * @return la taille du groupe
	 */
	public int getSize() {
		return members.size();
	}

	/**
	 * Recuperation des membres du groupe.
	 * 
	 * @return la liste des membres
	 */
	public List<Member> getMembers() {
		return members;
	}

	public int compareTo(Group o) {
		int res;
		if (o == null) {
			res = -1;
		} else {
			res = (int) Math.signum(getSize() - o.getSize());
		}
		return res;
	}

	public int compare(Group o1, Group o2) {
		return o1.compareTo(o2);
	}

	@Override
	public String toString() {
		return name;
	}
}
