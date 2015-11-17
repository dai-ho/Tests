package fr.free.hd.ruch.giftsrandomizer.people;

import java.util.ArrayList;
import java.util.List;

/**
 * Classe representant un participant
 * 
 * @author Vincent
 */
public class Member {
	/** Nom du participant */
	private String name;
	/** Conjoint eventuel */
	private Member partner;
	/** Liste d'exclusions */
	private List<Member> exclusions;
	/** Groupe auquel il appartient. */
	private Group group;

	/**
	 * Constructeur de base.
	 * 
	 * @param name nom de la personne (Marine, Vincent, ...)
	 * @param group groupe auquel il est associé (Convert, Ruch,...)
	 */
	public Member(String name, Group group) {
		this.name = name;
		if (group != null) {
			group.addMember(this);
			this.group = group;
		}
		exclusions = new ArrayList<Member>();
		exclusions.add(this);
	}

	public String getName() {
		return name;
	}

	public Member getPartner() {
		return partner;
	}

	public List<Member> getExclusions() {
		return exclusions;
	}

	public Group getGroup() {
		return group;
	}

	public void setGroup(Group g) {
		if (group != null) {
			group.getMembers().remove(this);
		}
		this.group = g;
		group.addMember(this);
	}

	public void exclude(Member m) {
		exclusions.add(m);
	}

	public void setPartner(Member partner) {
		this.partner = partner;
		if (partner.getPartner() == null) {
			partner.setPartner(this);
		}
	}

	@Override
	public String toString() {
		String s = name + "(" + super.toString() + ")";
		return s;
	}
}
