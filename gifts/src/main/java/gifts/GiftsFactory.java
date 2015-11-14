package gifts;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.math3.random.JDKRandomGenerator;

import people.Group;
import people.Member;

public class GiftsFactory {
	final ArrayList<Member> sample;
	final ArrayList<Group> groups;

	public GiftsFactory() {
		sample = new ArrayList<Member>();
		groups = new ArrayList<Group>();
	}

	public void addMember(Member m) {
		sample.add(m);
		if (!groups.contains(m.getGroup())) {
			groups.add(m.getGroup());
		}
	}

	public void addMembers(Member... m){
		for(Member mi:m){
			addMember(mi);
		}
	}
	// public List<Member> generateList() {
	// final JDKRandomGenerator g = new JDKRandomGenerator();
	// List<Member> randomList = new ArrayList<Member>();
	// int length = sample.size();
	// boolean ok = false;
	//
	// Integer j = g.nextInt(length);
	// Member mj = sample.get(j);
	// randomList.add(mj);
	// for (int i = 1; i < length; i++) {
	// while (!ok) {
	// j = g.nextInt(length);
	// mj = sample.get(j);
	// if (!randomList.contains(mj)) {
	// if (!mj.getPartner().equals(randomList.get(i - 1))) {
	// randomList.add(mj);
	// ok = true;
	// }
	// }
	// }
	// ok = false;
	// }
	// return randomList;
	// }

	@SuppressWarnings("unchecked")
	public Map<Member, Member> generateList2() {
		List<Member> given = new ArrayList<Member>(sample.size());
		Map<Member, Member> mapping = new HashMap<Member, Member>();
		final JDKRandomGenerator g = new JDKRandomGenerator();
		groups.sort(null);
		for (Group gr : groups) {
			List<Member> groupMembers = gr.getMembers();
			for (Member m1 : groupMembers) {
				List<Member> s = (List<Member>) sample.clone();
				clear(s, m1, given);
				s.removeAll(groupMembers);
				if (s.isEmpty()) {
					s.addAll(groupMembers);
					clear(s, m1, given);
				}
				if (s.isEmpty()) {
//					return mapping;
					return generateList2();
				}
				int i = g.nextInt(s.size());
				Member m2 = s.get(i);
				m2.exclude(m1);
				given.add(m2);
				mapping.put(m1, m2);
			}

		}
		return mapping;
	}

	private void clear(List<Member> s, Member m, List<Member> given) {
		if (m.getPartner() != null) {
			s.remove(m.getPartner());
		}
		s.removeAll(m.getExclusions());
		s.removeAll(given);
	}
}
